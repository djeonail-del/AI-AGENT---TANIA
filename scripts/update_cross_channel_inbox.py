#!/usr/bin/env python3
"""
update_cross_channel_inbox.py — Cross-channel inbox for real-time awareness

Scans the latest session JSONL files to find recent messages from non-Telegram-DM
channels (e.g. Discord) and updates memory/cross-channel-inbox.md.

Run on every message:received event via the cross-channel-inbox hook.
Keeps only last 20 entries.
"""

import json
import os
import re
import glob
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ─── Path detection ──────────────────────────────────────────────────────────

def _detect_workspace() -> str:
    if os.environ.get("WORKSPACE_DIR"):
        return os.environ["WORKSPACE_DIR"]
    if os.environ.get("OPENCLAW_WORKSPACE"):
        return os.environ["OPENCLAW_WORKSPACE"]
    if Path("/Users/mac/.openclaw/workspace").exists():
        return "/Users/mac/.openclaw/workspace"
    return str(Path(__file__).parent.parent)


def _detect_sessions(workspace_dir: str) -> str:
    if os.environ.get("OPENCLAW_SESSIONS"):
        return os.environ["OPENCLAW_SESSIONS"]
    candidates = [
        Path(workspace_dir).parent / "agents/main/sessions",
        Path("/Users/mac/.openclaw/agents/main/sessions"),
        Path("/root/.openclaw/agents/main/sessions"),
    ]
    return str(next((c for c in candidates if c.exists()), candidates[0]))


WORKSPACE_DIR = _detect_workspace()
SESSIONS_DIR = _detect_sessions(WORKSPACE_DIR)
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
INBOX_FILE = os.path.join(MEMORY_DIR, "cross-channel-inbox.md")
MAX_ENTRIES = 20
TELEGRAM_DM_SENDER = "832986465"  # Djeon's Telegram ID — skip this channel

# WIB = UTC+7
WIB = timezone(timedelta(hours=7))


# ─── Channel extraction ───────────────────────────────────────────────────────

def extract_channel_info(text: str) -> dict:
    result = {
        "channel_type": "unknown",
        "channel_label": "Unknown",
        "sender": "User",
        "is_telegram_dm": False,
    }

    if "[Subagent Context]" in text or "[Subagent Task]" in text:
        result["channel_type"] = "internal"
        return result

    if "Read HEARTBEAT.md" in text or "A new session was started via /new" in text:
        result["channel_type"] = "internal"
        return result

    conv_match = re.search(
        r'Conversation info \(untrusted metadata\):\s*```json\s*(\{.*?\})\s*```',
        text, re.DOTALL
    )
    meta = {}
    if conv_match:
        try:
            meta = json.loads(conv_match.group(1))
        except Exception:
            pass

    sender_match = re.search(
        r'Sender \(untrusted metadata\):\s*```json\s*(\{.*?\})\s*```',
        text, re.DOTALL
    )
    sender_meta = {}
    if sender_match:
        try:
            sender_meta = json.loads(sender_match.group(1))
        except Exception:
            pass

    if not meta:
        result["channel_type"] = "internal"
        return result

    sender_name = sender_meta.get("name") or meta.get("sender") or "User"
    sender_id = str(sender_meta.get("id") or meta.get("sender_id") or "")
    result["sender"] = sender_name

    conversation_label = meta.get("conversation_label", "")
    group_subject = meta.get("group_subject", "")
    is_group_chat = meta.get("is_group_chat", False)

    # Discord detection
    is_discord = "Guild" in conversation_label or group_subject.startswith("#")
    if is_discord:
        result["channel_type"] = "discord"
        short = group_subject.lstrip("#") if group_subject else "discord"
        result["channel_label"] = f"Discord #{short}"
        return result

    # Telegram group
    if is_group_chat:
        result["channel_type"] = "telegram_group"
        result["channel_label"] = f"Telegram: {group_subject}" if group_subject else "Telegram Group"
        return result

    # Telegram DM — check if it's Djeon's DM (skip)
    if sender_id == TELEGRAM_DM_SENDER or meta.get("chat_id") == f"telegram:{TELEGRAM_DM_SENDER}":
        result["channel_type"] = "telegram_dm"
        result["is_telegram_dm"] = True
        result["channel_label"] = "Telegram DM"
        return result

    # Other Telegram DM
    if meta.get("sender_id"):
        result["channel_type"] = "telegram_dm"
        result["channel_label"] = "Telegram DM"
        return result

    return result


def extract_message_body(text: str) -> str:
    """Extract just the actual message content."""
    # Try to get Discord untrusted body first
    m = re.search(
        r'UNTRUSTED Discord message body\s*(.*?)<<<END_EXTERNAL',
        text, re.DOTALL
    )
    if m:
        body = m.group(1).strip()
        if body and len(body) > 1:
            return body[:300]

    # Try Telegram untrusted body
    m = re.search(
        r'UNTRUSTED (?:Telegram|telegram) message body\s*(.*?)<<<END_EXTERNAL',
        text, re.DOTALL
    )
    if m:
        body = m.group(1).strip()
        if body and len(body) > 1:
            return body[:300]

    # Remove all metadata blocks
    clean = re.sub(r'Conversation info \(untrusted metadata\):.*?```\s*', '', text, flags=re.DOTALL)
    clean = re.sub(r'Sender \(untrusted metadata\):.*?```\s*', '', clean, flags=re.DOTALL)
    clean = re.sub(r'Untrusted context \(metadata[^)]*\):.*?<<<END_EXTERNAL[^>]*>>>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'<<<EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>.*?<<<END_EXTERNAL[^>]*>>>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'\[Queued messages.*?\]', '', clean, flags=re.DOTALL)
    clean = re.sub(r'System:.*?\n', '', clean)
    clean = re.sub(r'```json.*?```', '', clean, flags=re.DOTALL)
    clean = clean.strip()

    # First non-empty meaningful line (skip JSON artifacts and noise)
    skip_patterns = ('{', '"', '`', '---', 'json', 'Source:', 'UNTRUSTED', '<<<')
    for line in clean.split('\n'):
        line = line.strip()
        if (line and len(line) > 3
                and not any(line.startswith(p) for p in skip_patterns)
                and not re.match(r'^[\W_]+$', line)):  # not just symbols
            return line[:300]

    return ""


# ─── Scan recent Discord sessions ────────────────────────────────────────────

def get_recent_discord_messages(minutes: int = 30) -> list:
    """Scan JSONL files for Discord messages from the last N minutes."""
    cutoff_ts = datetime.now(timezone.utc).timestamp() - minutes * 60
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = [
        f for f in glob.glob(pattern)
        if ".reset." not in f and os.path.getmtime(f) >= cutoff_ts
    ]

    messages = []
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue

                    if entry.get("type") != "message":
                        continue

                    msg = entry.get("message", {})
                    if msg.get("role") != "user":
                        continue

                    ts_str = entry.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except Exception:
                        continue

                    # Only recent messages
                    if ts.timestamp() < cutoff_ts:
                        continue

                    content = msg.get("content", [])
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                        text = "\n".join(texts)
                    else:
                        continue

                    if not text:
                        continue

                    ch = extract_channel_info(text)

                    # Skip internal/subagent/heartbeat only — include ALL real channels
                    if ch["channel_type"] == "internal":
                        continue
                    if ch["channel_type"] == "unknown":
                        continue

                    body = extract_message_body(text)
                    if not body or len(body) < 2:
                        continue

                    messages.append({
                        "ts": ts,
                        "channel_label": ch["channel_label"],
                        "sender": ch["sender"],
                        "body": body,
                    })
        except Exception:
            continue

    # Sort by timestamp, deduplicate
    messages.sort(key=lambda m: m["ts"])
    seen = set()
    unique = []
    for m in messages:
        key = (m["channel_label"], m["sender"], m["body"][:50])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique


# ─── Update inbox file ────────────────────────────────────────────────────────

def read_existing_entries() -> list:
    """Read existing entries from inbox file."""
    if not os.path.exists(INBOX_FILE):
        return []
    entries = []
    with open(INBOX_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("**[") and "**" in line[3:]:
                entries.append(line)
    return entries


def format_entry(msg: dict) -> str:
    ts_wib = msg["ts"].astimezone(WIB)
    time_str = ts_wib.strftime("%H:%M WIB")
    return f"**[{time_str}]** [{msg['channel_label']}] **{msg['sender']}**: {msg['body']}"


def write_inbox(entries: list):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    now_wib = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
    header = f"""# 📥 Cross-Channel Inbox
_Last updated: {now_wib}_
_Recent messages from other channels (not current session)_

"""
    with open(INBOX_FILE, "w", encoding="utf-8") as f:
        f.write(header)
        for entry in entries[-MAX_ENTRIES:]:
            f.write(entry + "\n")


def main():
    new_messages = get_recent_discord_messages(minutes=60)

    if not new_messages:
        # Nothing new — touch the file to update mtime only if it doesn't exist
        if not os.path.exists(INBOX_FILE):
            write_inbox([])
        return

    # Load existing entries
    existing = read_existing_entries()

    # Format new messages
    new_entries = [format_entry(m) for m in new_messages]

    # Merge: add new entries not already in existing
    existing_set = set(existing)
    added = [e for e in new_entries if e not in existing_set]

    if not added:
        return  # Nothing new to add

    combined = existing + added
    # Keep last MAX_ENTRIES
    combined = combined[-MAX_ENTRIES:]

    write_inbox(combined)
    print(f"✅ Inbox updated: +{len(added)} new entries", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
unified_timeline.py — Cross-channel unified timeline for Tania

Scans all sessions from the last 24 hours, extracts ALL messages with
channel metadata, and saves a chronological cross-channel timeline to
memory/unified-timeline.md.

Usage: python3 scripts/unified_timeline.py [--hours <n>] [--output <file>]
"""

import json
import os
import re
import sys
import glob
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ─── Path detection (same pattern as save_last_conversation.py) ───────────────

def _detect_workspace() -> str:
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
    try:
        home = Path.home()
        for d in home.iterdir():
            if d.name.endswith("-openclaw") and (d / "agents/main/sessions").exists():
                candidates.append(d / "agents/main/sessions")
    except Exception:
        pass
    return str(next((c for c in candidates if c.exists()), candidates[0]))


WORKSPACE_DIR = _detect_workspace()
SESSIONS_DIR = _detect_sessions(WORKSPACE_DIR)
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
DEFAULT_OUTPUT = os.path.join(MEMORY_DIR, "unified-timeline.md")
DEFAULT_HOURS = 24
MAX_TIMELINE_ENTRIES = 500   # cap to prevent enormous output
MAX_TEXT_PREVIEW = 120       # characters per message in timeline


# ─── Channel Extraction ───────────────────────────────────────────────────────

def extract_channel_info(text: str) -> dict:
    """
    Parse channel metadata from user message text.

    Returns a dict with keys:
      - channel_type: "telegram_dm" | "telegram_group" | "discord" | "internal" | "unknown"
      - channel_label: Human-readable label, e.g. "Telegram DM", "Discord #ops-monitoring"
      - channel_key: Short stable key for grouping, e.g. "telegram_dm", "discord_ops-monitoring"
      - sender: Display name of the sender
      - is_group: bool
    """
    result = {
        "channel_type": "unknown",
        "channel_label": "Unknown",
        "channel_key": "unknown",
        "sender": "User",
        "is_group": False,
    }

    # Special: Subagent tasks
    if "[Subagent Context]" in text or "[Subagent Task]" in text:
        result["channel_type"] = "internal"
        result["channel_label"] = "Subagent"
        result["channel_key"] = "internal_subagent"
        result["sender"] = "Subagent"
        return result

    # Special: Heartbeat / system
    if "Read HEARTBEAT.md" in text or "A new session was started via /new" in text:
        result["channel_type"] = "internal"
        result["channel_label"] = "Heartbeat"
        result["channel_key"] = "internal_heartbeat"
        result["sender"] = "System"
        return result

    # Extract Conversation info JSON block
    conv_match = re.search(
        r'Conversation info \(untrusted metadata\):\s*```json\s*(\{.*?\})\s*```',
        text, re.DOTALL
    )
    if not conv_match:
        conv_match = re.search(r'(\{[^{}]*"sender_id"[^{}]*\})', text, re.DOTALL)

    meta = {}
    if conv_match:
        try:
            meta = json.loads(conv_match.group(1))
        except Exception:
            pass

    # Extract Sender metadata
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

    sender_name = (
        sender_meta.get("name") or
        meta.get("sender") or
        "User"
    )
    result["sender"] = sender_name

    if not meta:
        result["channel_type"] = "internal"
        result["channel_label"] = "Internal"
        result["channel_key"] = "internal"
        result["sender"] = "System"
        return result

    conversation_label = meta.get("conversation_label", "")
    group_subject = meta.get("group_subject", "")
    is_group_chat = meta.get("is_group_chat", False)

    # Discord detection
    is_discord = (
        "Guild" in conversation_label or
        group_subject.startswith("#")
    )

    if is_discord:
        result["channel_type"] = "discord"
        result["is_group"] = True
        if group_subject:
            # Shorten label for display
            short = group_subject.lstrip("#")
            result["channel_label"] = f"Discord #{short}"
            result["channel_key"] = f"discord_{short.replace(' ', '-').lower()}"
        else:
            result["channel_label"] = "Discord"
            result["channel_key"] = "discord"
        return result

    # Telegram group
    if is_group_chat:
        result["channel_type"] = "telegram_group"
        result["is_group"] = True
        if group_subject:
            result["channel_label"] = f"Telegram: {group_subject}"
            result["channel_key"] = f"telegram_group_{group_subject.replace(' ', '-').lower()}"
        else:
            result["channel_label"] = "Telegram Group"
            result["channel_key"] = "telegram_group"
        return result

    # Telegram DM
    if meta.get("sender_id"):
        result["channel_type"] = "telegram_dm"
        result["channel_label"] = "Telegram DM"
        result["channel_key"] = "telegram_dm"
        result["is_group"] = False
        return result

    return result


def extract_message_text(text: str, max_len: int = MAX_TEXT_PREVIEW) -> str:
    """Extract the actual human message text, stripping metadata blocks."""
    # Remove "Conversation info (untrusted metadata):" JSON block
    cleaned = re.sub(
        r'Conversation info \(untrusted metadata\):\s*```json.*?```\s*',
        '', text, flags=re.DOTALL
    )
    # Remove "Sender (untrusted metadata):" JSON block
    cleaned = re.sub(
        r'Sender \(untrusted metadata\):\s*```json.*?```\s*',
        '', cleaned, flags=re.DOTALL
    )
    # Remove "Untrusted context" blocks
    cleaned = re.sub(
        r'Untrusted context.*?<<<END_EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>',
        '', cleaned, flags=re.DOTALL
    )
    # Remove "[Subagent Context]..." preamble
    cleaned = re.sub(r'\[.*? Context\].*?(?=\n\n|\Z)', '', cleaned, flags=re.DOTALL)

    cleaned = cleaned.strip()

    # Collapse multiple blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    # Take first non-empty line as preview
    first_line = ""
    for line in cleaned.split('\n'):
        line = line.strip()
        if line:
            first_line = line
            break

    if not first_line:
        first_line = cleaned[:max_len].strip()

    if len(first_line) > max_len:
        return first_line[:max_len] + "…"
    return first_line


# ─── Session scanning ─────────────────────────────────────────────────────────

def find_sessions(hours: float = DEFAULT_HOURS) -> list[str]:
    """Find all .jsonl session files modified within the last N hours."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    cutoff = datetime.now().timestamp() - hours * 3600
    files = [
        f for f in glob.glob(pattern)
        if ".reset." not in f and os.path.getmtime(f) >= cutoff
    ]
    return sorted(files, key=os.path.getmtime)


def parse_session_for_timeline(filepath: str) -> list[dict]:
    """
    Parse a JSONL session file and return all messages with channel metadata.
    Returns list of dicts with: role, text_preview, full_text, timestamp, channel_info, session_id
    """
    messages = []
    session_meta = {}
    last_user_channel = None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")

                if entry_type == "session":
                    session_meta = entry
                    continue

                if entry_type != "message":
                    continue

                msg = entry.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                # Extract text
                content_parts = msg.get("content", [])
                if isinstance(content_parts, str):
                    text = content_parts.strip()
                else:
                    texts = []
                    for part in content_parts:
                        if isinstance(part, dict) and part.get("type") == "text":
                            texts.append(part.get("text", "").strip())
                    text = "\n".join(texts).strip()

                if not text:
                    continue

                timestamp_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except Exception:
                    ts = None

                # Channel info
                if role == "user":
                    channel_info = extract_channel_info(text)
                    last_user_channel = channel_info
                else:
                    if last_user_channel:
                        channel_info = {
                            "channel_type": last_user_channel["channel_type"],
                            "channel_label": last_user_channel["channel_label"],
                            "channel_key": last_user_channel["channel_key"],
                            "sender": "Tania",
                            "is_group": last_user_channel["is_group"],
                        }
                    else:
                        channel_info = {
                            "channel_type": "unknown",
                            "channel_label": "Unknown",
                            "channel_key": "unknown",
                            "sender": "Tania",
                            "is_group": False,
                        }

                text_preview = extract_message_text(text) if role == "user" else text[:MAX_TEXT_PREVIEW].replace("\n", " ")
                if len(text_preview) < len(text[:MAX_TEXT_PREVIEW]):
                    pass  # preview already handles truncation

                messages.append({
                    "role": role,
                    "text_preview": text_preview,
                    "full_text": text,
                    "timestamp": ts,
                    "timestamp_raw": timestamp_str,
                    "session_file": os.path.basename(filepath),
                    "session_id": session_meta.get("id", os.path.basename(filepath)),
                    "channel_info": channel_info,
                })
    except Exception as e:
        print(f"   ⚠️  Error parsing {os.path.basename(filepath)}: {e}", file=sys.stderr)

    return messages


# ─── Report generation ────────────────────────────────────────────────────────

def build_channel_summary(messages: list[dict]) -> dict:
    """
    Build per-channel stats.
    Returns dict: channel_key → {label, count, last_ts, first_ts}
    """
    stats = {}
    for msg in messages:
        ci = msg["channel_info"]
        key = ci.get("channel_key", "unknown")
        label = ci.get("channel_label", "Unknown")
        ts = msg["timestamp"]

        if key not in stats:
            stats[key] = {"label": label, "count": 0, "last_ts": None, "first_ts": None}

        stats[key]["count"] += 1
        if ts:
            if stats[key]["last_ts"] is None or ts > stats[key]["last_ts"]:
                stats[key]["last_ts"] = ts
            if stats[key]["first_ts"] is None or ts < stats[key]["first_ts"]:
                stats[key]["first_ts"] = ts

    return stats


def format_timeline_md(
    messages: list[dict],
    session_files: list[str],
    hours_scanned: float,
    output_date: str,
) -> str:
    """Format the unified timeline as markdown."""

    # Filter to real channels only (exclude pure internal)
    real_messages = [
        m for m in messages
        if m["channel_info"]["channel_type"] not in ("internal",)
    ]

    # Sort chronologically
    real_messages.sort(
        key=lambda m: m["timestamp"] or datetime.min.replace(tzinfo=timezone.utc)
    )

    # Cap
    if len(real_messages) > MAX_TIMELINE_ENTRIES:
        real_messages = real_messages[-MAX_TIMELINE_ENTRIES:]

    channel_stats = build_channel_summary(real_messages)

    saved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# 🌐 Unified Timeline — {output_date}",
        "",
        f"_Generated: {saved_at} · Sessions from last {hours_scanned}h · {len(session_files)} file(s)_",
        "",
        "## Summary",
        "",
    ]

    # Sort channels: telegram_dm first, then discord channels, then others
    def channel_sort_key(item):
        key, stats = item
        order = {"telegram_dm": 0, "discord": 1, "telegram_group": 2}
        ct = key.split("_")[0] if "_" in key else key
        return (order.get(ct, 9), stats["label"])

    for key, stats in sorted(channel_stats.items(), key=channel_sort_key):
        label = stats["label"]
        count = stats["count"]
        last_str = stats["last_ts"].strftime("%H:%M") if stats["last_ts"] else "?"
        lines.append(f"- **{label}**: {count} messages (last: {last_str})")

    if not channel_stats:
        lines.append("_No messages found in the specified time window._")

    lines += ["", "---", "", "## Timeline (chronological, all channels)", ""]

    if not real_messages:
        lines.append("_No messages to display._")
    else:
        prev_date = None
        for msg in real_messages:
            ts = msg["timestamp"]
            ci = msg["channel_info"]
            label = ci.get("channel_label", "Unknown")
            sender = ci.get("sender", "?")
            text_preview = msg["text_preview"]

            # Date divider
            if ts:
                msg_date = ts.strftime("%Y-%m-%d")
                if msg_date != prev_date:
                    lines.append(f"### 📅 {msg_date}")
                    lines.append("")
                    prev_date = msg_date

            ts_str = ts.strftime("%H:%M") if ts else "??"

            # Escape any markdown special chars in preview (keep it clean)
            preview_clean = text_preview.replace("**", "").replace("__", "").strip()
            if len(preview_clean) > MAX_TEXT_PREVIEW:
                preview_clean = preview_clean[:MAX_TEXT_PREVIEW] + "…"

            lines.append(f"**[{ts_str}] {label}** — {sender}: {preview_clean}")

    lines += ["", "---", ""]
    lines.append(f"_Total: {len(real_messages)} messages across {len(channel_stats)} channel(s)_")
    lines.append("")

    return "\n".join(lines)


def main():
    hours = DEFAULT_HOURS
    output_file = DEFAULT_OUTPUT

    if "--hours" in sys.argv:
        idx = sys.argv.index("--hours")
        if idx + 1 < len(sys.argv):
            try:
                hours = float(sys.argv[idx + 1])
            except ValueError:
                pass

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]

    # Ensure memory dir
    os.makedirs(MEMORY_DIR, exist_ok=True)

    print(f"🌐 Building unified timeline (last {hours}h)...")
    print(f"   Sessions dir: {SESSIONS_DIR}")

    session_files = find_sessions(hours)
    if not session_files:
        print(f"⚠️  No session files found in last {hours}h")
        # Write empty timeline
        today = datetime.now().strftime("%Y-%m-%d")
        content = (
            f"# 🌐 Unified Timeline — {today}\n\n"
            f"_No sessions found in the last {hours}h._\n"
        )
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Saved empty timeline: {output_file}")
        return

    print(f"   Found {len(session_files)} session file(s)")

    # Parse all sessions
    all_messages = []
    for sf in session_files:
        msgs = parse_session_for_timeline(sf)
        all_messages.extend(msgs)
        if msgs:
            # Show channel breakdown for this session
            channels = set(m["channel_info"]["channel_label"] for m in msgs)
            print(f"   {os.path.basename(sf)}: {len(msgs)} msgs → {', '.join(sorted(channels))}")

    print(f"   Total messages: {len(all_messages)}")

    # Build and write timeline
    today = datetime.now().strftime("%Y-%m-%d")
    md_content = format_timeline_md(all_messages, session_files, hours, today)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"✅ Saved: {output_file}")

    # Preview
    preview_lines = md_content.split("\n")[:50]
    print("\n--- Preview (first 50 lines) ---")
    print("\n".join(preview_lines))
    print("--- End preview ---")


if __name__ == "__main__":
    main()

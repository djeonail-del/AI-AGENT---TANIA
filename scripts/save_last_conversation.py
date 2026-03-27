#!/usr/bin/env python3
"""
save_last_conversation.py — Save last 30 messages from ALL recent sessions
(within last 4 hours) to memory/last-conversation.md for seamless continuity
across resets. Also captures subagent work from separate JSONL files.

Phase 2: Channel-aware — each message is tagged with its source channel
(Telegram DM, Discord #channel, Telegram Group, internal, etc.)

Usage: python3 scripts/save_last_conversation.py [--session <file>] [--hours <n>]
"""

import json
import os
import re
import sys
import glob
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _detect_workspace() -> str:
    if os.environ.get("OPENCLAW_WORKSPACE"):
        return os.environ["OPENCLAW_WORKSPACE"]
    if Path("/Users/mac/.openclaw/workspace").exists():
        return "/Users/mac/.openclaw/workspace"
    # VPS: scripts/ lives inside workspace/
    return str(Path(__file__).parent.parent)


def _detect_sessions(workspace_dir: str) -> str:
    if os.environ.get("OPENCLAW_SESSIONS"):
        return os.environ["OPENCLAW_SESSIONS"]
    candidates = [
        Path(workspace_dir).parent / "agents/main/sessions",
        Path("/Users/mac/.openclaw/agents/main/sessions"),
        Path("/root/.openclaw/agents/main/sessions"),
    ]
    # Also check agent-specific paths like /root/.nara-openclaw/agents/main/sessions
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
OUTPUT_FILE = os.path.join(WORKSPACE_DIR, "memory", "last-conversation.md")
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")
MAX_MESSAGES = 30
MAX_MSG_LENGTH = 2000  # truncate very long messages in the markdown
DEFAULT_HOURS = 4      # scan all files modified within this window


# ─── Channel Extraction ───────────────────────────────────────────────────────

def extract_channel_info(text: str) -> dict:
    """
    Parse channel metadata from user message text.

    OpenClaw embeds untrusted metadata as JSON blocks in user messages.
    This function extracts channel identity, channel name, and sender name.

    Returns a dict with keys:
      - channel_type: "telegram_dm" | "telegram_group" | "discord" | "internal" | "unknown"
      - channel_label: Human-readable label, e.g. "[Telegram DM]", "[Discord #ops-monitoring]"
      - sender: Display name of the sender
      - is_group: bool
    """
    # Default
    result = {
        "channel_type": "unknown",
        "channel_label": "[unknown]",
        "sender": "User",
        "is_group": False,
    }

    # Special: Subagent tasks
    if "[Subagent Context]" in text or "[Subagent Task]" in text:
        result["channel_type"] = "internal"
        result["channel_label"] = "[Subagent]"
        result["sender"] = "Subagent"
        return result

    # Special: Heartbeat / session reset / system messages
    if ("Read HEARTBEAT.md" in text or
            "A new session was started via /new" in text or
            "HEARTBEAT_OK" in text):
        result["channel_type"] = "internal"
        result["channel_label"] = "[Heartbeat]"
        result["sender"] = "System"
        return result

    # Try to extract the JSON metadata block from "Conversation info (untrusted metadata):"
    # Pattern: ```json ... ``` block after "Conversation info"
    conv_match = re.search(
        r'Conversation info \(untrusted metadata\):\s*```json\s*(\{.*?\})\s*```',
        text, re.DOTALL
    )
    if not conv_match:
        # Try to find any JSON block with sender_id
        conv_match = re.search(r'(\{[^{}]*"sender_id"[^{}]*\})', text, re.DOTALL)

    if conv_match:
        try:
            meta = json.loads(conv_match.group(1))
        except Exception:
            meta = {}
    else:
        meta = {}

    # Extract sender name from Sender metadata block too
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

    # Get sender name (prefer sender_meta name, fall back to meta sender)
    sender_name = (
        sender_meta.get("name") or
        meta.get("sender") or
        "User"
    )
    result["sender"] = sender_name

    if not meta:
        # No metadata found — classify as internal/unknown
        result["channel_type"] = "internal"
        result["channel_label"] = "[internal]"
        result["sender"] = "System"
        return result

    # Determine channel type
    conversation_label = meta.get("conversation_label", "")
    group_subject = meta.get("group_subject", "")
    is_group_chat = meta.get("is_group_chat", False)

    # Discord detection: conversation_label contains "Guild" OR group_subject starts with "#"
    is_discord = (
        "Guild" in conversation_label or
        (group_subject.startswith("#"))
    )

    if is_discord:
        result["channel_type"] = "discord"
        result["is_group"] = True
        if group_subject:
            result["channel_label"] = f"[Discord {group_subject}]"
        else:
            result["channel_label"] = "[Discord]"
        return result

    # Telegram group detection: is_group_chat = true and not Discord
    if is_group_chat:
        result["channel_type"] = "telegram_group"
        result["is_group"] = True
        if group_subject:
            result["channel_label"] = f"[Telegram Group: {group_subject}]"
        else:
            result["channel_label"] = "[Telegram Group]"
        return result

    # Telegram DM: has sender_id, not a group
    if meta.get("sender_id"):
        result["channel_type"] = "telegram_dm"
        result["channel_label"] = "[Telegram DM]"
        result["is_group"] = False
        return result

    return result


def find_latest_session():
    """Find the most recently modified .jsonl session file."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = [f for f in glob.glob(pattern) if ".reset." not in f]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def find_recent_sessions(hours=DEFAULT_HOURS):
    """Find all .jsonl session files modified within the last N hours."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    cutoff = datetime.now().timestamp() - hours * 3600
    files = [
        f for f in glob.glob(pattern)
        if ".reset." not in f and os.path.getmtime(f) >= cutoff
    ]
    return sorted(files, key=os.path.getmtime)


def parse_session(filepath):
    """Parse a JSONL session file and extract user/assistant text messages."""
    messages = []
    session_meta = {}
    last_user_channel = None  # track for inferring assistant channel

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

            # Capture session metadata
            if entry_type == "session":
                session_meta = entry
                continue

            # Only process message entries
            if entry_type != "message":
                continue

            msg = entry.get("message", {})
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            # Extract text content only (skip tool_use, tool_result, etc.)
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

            # ── Channel extraction ────────────────────────────────────────────
            if role == "user":
                channel_info = extract_channel_info(text)
                last_user_channel = channel_info  # remember for assistant messages
            else:
                # Assistant inherits channel from preceding user message in this session
                if last_user_channel:
                    channel_info = {
                        "channel_type": last_user_channel["channel_type"],
                        "channel_label": last_user_channel["channel_label"],
                        "sender": "Tania",
                        "is_group": last_user_channel["is_group"],
                    }
                else:
                    channel_info = {
                        "channel_type": "unknown",
                        "channel_label": "[unknown]",
                        "sender": "Tania",
                        "is_group": False,
                    }

            messages.append({
                "role": role,
                "text": text,
                "timestamp": ts,
                "timestamp_raw": timestamp_str,
                "session_file": os.path.basename(filepath),
                "session_id": session_meta.get("id", os.path.basename(filepath)),
                "channel_info": channel_info,
            })

    return session_meta, messages


def truncate(text, max_len=MAX_MSG_LENGTH):
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n_[truncated — {len(text) - max_len} more chars]_"


def build_channel_activity_summary(messages: list) -> list[str]:
    """
    Build a 'Channel Activity' summary showing which channels were active.
    Returns a list of markdown lines.
    """
    from collections import defaultdict, Counter

    channel_stats = defaultdict(lambda: {"count": 0, "last_ts": None, "label": ""})

    for msg in messages:
        ci = msg.get("channel_info", {})
        label = ci.get("channel_label", "[unknown]")
        ts = msg.get("timestamp")

        channel_stats[label]["count"] += 1
        channel_stats[label]["label"] = label
        if ts and (channel_stats[label]["last_ts"] is None or ts > channel_stats[label]["last_ts"]):
            channel_stats[label]["last_ts"] = ts

    if not channel_stats:
        return []

    lines = ["## 📡 Channel Activity", ""]
    for label, stats in sorted(channel_stats.items()):
        last_str = ""
        if stats["last_ts"]:
            last_str = f" — last: {stats['last_ts'].strftime('%H:%M UTC')}"
        lines.append(f"- **{label}**: {stats['count']} messages{last_str}")
    lines.append("")
    lines.append("---")
    lines.append("")

    return lines


def format_markdown(messages, session_files, hours_scanned):
    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 💬 Last Conversation",
        "",
        f"**Sessions scanned:** {len(session_files)} file(s) from last {hours_scanned}h  ",
        f"**Saved:** {saved_at} (local)  ",
        f"**Messages captured:** {len(messages)} (last {MAX_MESSAGES} user+assistant turns)",
        "",
    ]

    if session_files:
        lines.append("**Files:**")
        for sf in session_files:
            lines.append(f"- `{os.path.basename(sf)}`")
        lines.append("")

    lines += ["---", ""]

    # Channel Activity summary (Phase 2)
    channel_summary = build_channel_activity_summary(messages)
    if channel_summary:
        lines.extend(channel_summary)

    prev_session = None
    for msg in messages:
        # Show session divider when session changes
        cur_session = msg.get("session_id", "")
        if cur_session != prev_session:
            if prev_session is not None:
                lines += ["", "> _(session boundary)_", ""]
            prev_session = cur_session

        role = msg["role"]
        ts = msg["timestamp"]
        ts_label = ts.strftime("%H:%M UTC") if ts else ""
        ci = msg.get("channel_info", {})
        channel_label = ci.get("channel_label", "")
        sender = ci.get("sender", "")

        if role == "user":
            role_icon = f"🧑 **{sender}**" if sender and sender not in ("User", "System") else "🧑 **User**"
        else:
            role_icon = "🤖 **Tania**"

        # Phase 2: include channel label in header
        if channel_label and channel_label not in ("[unknown]", "[internal]", "[Heartbeat]", "[Subagent]"):
            lines.append(f"### {role_icon} {channel_label}  <sub>{ts_label}</sub>")
        else:
            lines.append(f"### {role_icon}  <sub>{ts_label}</sub>")

        lines.append("")
        lines.append(truncate(msg["text"]))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


HEARTBEAT_STATE_FILE = os.path.join(WORKSPACE_DIR, "memory", "heartbeat-state.json")


def load_heartbeat_state() -> dict:
    """Load heartbeat-state.json, returning empty dict if missing/corrupt."""
    if os.path.exists(HEARTBEAT_STATE_FILE):
        try:
            with open(HEARTBEAT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_heartbeat_state(state: dict):
    """Save heartbeat-state.json."""
    os.makedirs(os.path.dirname(HEARTBEAT_STATE_FILE), exist_ok=True)
    with open(HEARTBEAT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def append_daily_summary(messages, session_files, hours_scanned):
    """Append a brief summary block to today's daily memory file.

    Dedup guard (session-ID based):
    - Tracks which session IDs have already been appended today in heartbeat-state.json
    - Key: appended_sessions → { "YYYY-MM-DD": [session_id1, ...] }
    - Skips sessions already appended today; only writes new ones.
    - Cleans up entries older than 7 days to keep the state file lean.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = os.path.join(MEMORY_DIR, f"{today}.md")

    # ── Extract session IDs from session files ────────────────────────────────
    all_session_ids = [
        os.path.basename(sf).replace(".jsonl", "") for sf in session_files
    ]

    # ── Load state & dedup check ──────────────────────────────────────────────
    state = load_heartbeat_state()
    appended = state.get("appended_sessions", {})

    # Clean up old dates (keep only last 7 days)
    from datetime import date, timedelta
    cutoff_date = (date.today() - timedelta(days=7)).isoformat()
    appended = {d: ids for d, ids in appended.items() if d >= cutoff_date}

    today_appended = set(appended.get(today, []))
    new_session_ids = [sid for sid in all_session_ids if sid not in today_appended]

    if not new_session_ids:
        print(
            f"⏭  All {len(all_session_ids)} session(s) already appended today "
            f"(session-ID dedup) — skipping duplicate append"
        )
        return daily_file

    # Only include messages from new sessions
    new_session_set = set(new_session_ids)
    new_messages = [m for m in messages if m.get("session_id", "").replace(".jsonl", "") in new_session_set]
    if not new_messages:
        new_messages = messages  # fallback: include all if we can't filter

    new_session_files = [sf for sf in session_files
                         if os.path.basename(sf).replace(".jsonl", "") in new_session_set]

    user_count = sum(1 for m in new_messages if m["role"] == "user")
    asst_count = sum(1 for m in new_messages if m["role"] == "assistant")

    # First and last timestamps
    all_ts = [m["timestamp_raw"] for m in new_messages if m["timestamp_raw"]]
    first_ts = all_ts[0] if all_ts else "?"
    last_ts = all_ts[-1] if all_ts else "?"

    # Sample topics from first user messages
    samples = [m["text"][:80].replace("\n", " ") for m in new_messages if m["role"] == "user"][:3]
    topic_snippet = " | ".join(samples) if samples else "(no user messages)"

    # Channel activity summary for daily notes
    from collections import defaultdict
    channel_counts = defaultdict(int)
    for m in new_messages:
        ci = m.get("channel_info", {})
        label = ci.get("channel_label", "[unknown]")
        channel_counts[label] += 1
    channel_summary_str = ", ".join(f"{lbl}: {cnt}" for lbl, cnt in sorted(channel_counts.items()))

    file_list = "\n".join(f"  - `{os.path.basename(sf)}`" for sf in new_session_files)

    summary_block = (
        f"\n## 📝 Conversation Summary (auto-saved {datetime.now().strftime('%H:%M')})\n"
        f"- **Sessions scanned (last {hours_scanned}h):** {len(new_session_files)}\n"
        f"{file_list}\n"
        f"- **Messages:** {user_count} user, {asst_count} assistant\n"
        f"- **Range:** {first_ts} → {last_ts}\n"
        f"- **Channels:** {channel_summary_str}\n"
        f"- **Topics (sample):** {topic_snippet}\n"
    )

    # Append to daily file (create if missing)
    with open(daily_file, "a", encoding="utf-8") as f:
        f.write(summary_block)

    # ── Update heartbeat state ────────────────────────────────────────────────
    today_list = list(today_appended) + new_session_ids
    appended[today] = today_list
    state["appended_sessions"] = appended
    save_heartbeat_state(state)
    print(f"   Recorded {len(new_session_ids)} new session(s) in heartbeat-state.json")

    return daily_file


def main():
    # Allow --session override (single file, legacy mode)
    session_file = None
    hours = DEFAULT_HOURS

    if "--session" in sys.argv:
        idx = sys.argv.index("--session")
        if idx + 1 < len(sys.argv):
            session_file = sys.argv[idx + 1]

    if "--hours" in sys.argv:
        idx = sys.argv.index("--hours")
        if idx + 1 < len(sys.argv):
            try:
                hours = float(sys.argv[idx + 1])
            except ValueError:
                pass

    # Ensure memory dir exists
    os.makedirs(MEMORY_DIR, exist_ok=True)

    if session_file:
        # Legacy single-file mode
        if not os.path.exists(session_file):
            print(f"ERROR: Session file not found: {session_file}", file=sys.stderr)
            sys.exit(1)
        session_files = [session_file]
        print(f"📂 Single-session mode: {os.path.basename(session_file)}")
    else:
        # Multi-session mode: scan all files within the time window
        session_files = find_recent_sessions(hours)
        if not session_files:
            # Fallback: use latest session regardless of age
            latest = find_latest_session()
            if latest:
                session_files = [latest]
                print(f"⚠️  No sessions in last {hours}h — using latest: {os.path.basename(latest)}")
            else:
                print(f"ERROR: No session files found in {SESSIONS_DIR}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"📂 Found {len(session_files)} session(s) modified in last {hours}h:")
            for sf in session_files:
                age_min = (datetime.now().timestamp() - os.path.getmtime(sf)) / 60
                print(f"   [{age_min:.0f}m ago] {os.path.basename(sf)}")

    # Parse all session files, collect all messages
    all_messages = []
    for sf in session_files:
        meta, msgs = parse_session(sf)
        print(f"   {os.path.basename(sf)}: {len(msgs)} user+assistant messages")
        all_messages.extend(msgs)

    # Sort by timestamp (messages with None timestamp go to front)
    all_messages.sort(key=lambda m: m["timestamp"] or datetime.min.replace(tzinfo=timezone.utc))

    print(f"   Total messages across all sessions: {len(all_messages)}")

    # Take last N messages
    messages = all_messages[-MAX_MESSAGES:]
    print(f"   Keeping last {len(messages)} messages")

    # Write last-conversation.md
    md_content = format_markdown(messages, session_files, hours)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"✅ Saved: {OUTPUT_FILE}")

    # Append summary to daily notes
    daily_file = append_daily_summary(messages, session_files, hours)
    print(f"✅ Appended summary to: {daily_file}")

    # Show preview
    preview_lines = md_content.split("\n")[:40]
    print("\n--- Preview (first 40 lines) ---")
    print("\n".join(preview_lines))
    print("--- End preview ---")


if __name__ == "__main__":
    main()

# ─── Post-save: update SQLite FTS index ───────────────────────────────────────
# Re-indexes sessions modified in the last 4 hours to catch new/updated sessions.
import subprocess as _subprocess
_script_dir = os.path.dirname(os.path.abspath(__file__))
_indexer = os.path.join(_script_dir, "session_indexer.py")
if os.path.exists(_indexer):
    try:
        _subprocess.run(
            [sys.executable, _indexer, "--since", "4h"],
            capture_output=True,
            timeout=30
        )
    except Exception:
        pass  # Silent fail — indexing is best-effort

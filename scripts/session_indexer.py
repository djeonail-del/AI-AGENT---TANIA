#!/usr/bin/env python3
"""
session_indexer.py — SQLite FTS5 full-text search index for OpenClaw sessions.

Usage:
  python3 session_indexer.py index              — index all sessions (skips already indexed)
  python3 session_indexer.py search "query" [--limit N]  — search messages
  python3 session_indexer.py stats              — show DB stats
  python3 session_indexer.py reindex            — force re-index everything
"""

import json
import os
import sys
import glob
import sqlite3
import argparse
from datetime import datetime, timezone

def _detect_workspace_si() -> str:
    if os.environ.get("OPENCLAW_WORKSPACE") or os.environ.get("WORKSPACE_DIR"):
        return os.environ.get("OPENCLAW_WORKSPACE") or os.environ.get("WORKSPACE_DIR")
    if os.path.exists("/Users/mac/.openclaw/workspace"):
        return "/Users/mac/.openclaw/workspace"
    from pathlib import Path as _P
    return str(_P(__file__).parent.parent)


def _detect_sessions_si(workspace: str) -> str:
    if os.environ.get("OPENCLAW_SESSIONS"):
        return os.environ["OPENCLAW_SESSIONS"]
    from pathlib import Path as _P
    candidates = [
        _P(workspace).parent / "agents/main/sessions",
        _P("/Users/mac/.openclaw/agents/main/sessions"),
        _P("/root/.openclaw/agents/main/sessions"),
    ]
    try:
        home = _P.home()
        for d in home.iterdir():
            if d.name.endswith("-openclaw") and (d / "agents/main/sessions").exists():
                candidates.append(d / "agents/main/sessions")
    except Exception:
        pass
    return str(next((c for c in candidates if c.exists()), candidates[0]))


WORKSPACE_DIR = _detect_workspace_si()
SESSIONS_DIR = _detect_sessions_si(WORKSPACE_DIR)
DB_PATH = os.path.join(WORKSPACE_DIR, "memory", "sessions.db")


# ─── DB Setup ──────────────────────────────────────────────────────────────────

def get_db(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions_meta (
            session_id   TEXT PRIMARY KEY,
            file_path    TEXT,
            started_at   TEXT,
            message_count INTEGER,
            indexed_at   TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            session_id,
            role,
            content,
            timestamp,
            tokenize='porter unicode61'
        );
    """)
    conn.commit()


# ─── Parsing ───────────────────────────────────────────────────────────────────

def parse_session_file(filepath):
    """
    Parse a JSONL session file.
    Returns (session_meta dict, list of message dicts).
    Handles malformed JSONL gracefully.
    """
    messages = []
    session_meta = {}

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip malformed lines

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

                # Extract plain text only (skip tool_use, tool_result, etc.)
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
                messages.append({
                    "role": role,
                    "content": text,
                    "timestamp": timestamp_str,
                })
    except OSError as e:
        print(f"  ⚠ Could not read {filepath}: {e}", file=sys.stderr)

    return session_meta, messages


def extract_session_id(filepath, session_meta):
    """Get session_id from meta or fall back to filename."""
    sid = session_meta.get("id")
    if not sid:
        sid = os.path.splitext(os.path.basename(filepath))[0]
        # strip .reset.* suffix if present
        if ".reset." in sid:
            sid = sid.split(".reset.")[0]
    return sid


# ─── Commands ──────────────────────────────────────────────────────────────────

def cmd_index(force=False, since_ts=None):
    """Index all sessions. Skips already-indexed ones unless force=True.

    Args:
        force: If True, re-index everything (ignores existing index entries).
        since_ts: If set (Unix timestamp float), only process files modified at or after
                  this time. Already-indexed sessions in this window are re-indexed.
                  Use --since flag to trigger this (e.g. --since 4h).
    """
    conn = get_db()
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No session files found in {SESSIONS_DIR}")
        conn.close()
        return

    # Filter by mtime when --since is specified
    if since_ts is not None:
        files = [f for f in files if os.path.getmtime(f) >= since_ts]
        print(f"  --since filter: {len(files)} file(s) modified after {datetime.fromtimestamp(since_ts).isoformat()}")

    total_indexed = 0
    total_skipped = 0
    total_messages = 0
    errors = []

    for filepath in files:
        # Skip .reset. backup files — they're duplicates
        if ".reset." in os.path.basename(filepath):
            continue

        session_meta, messages = parse_session_file(filepath)
        session_id = extract_session_id(filepath, session_meta)

        # Check if already indexed — skip only when NOT using --since/force
        # (--since mode always re-indexes matched files to pick up new messages)
        if not force and since_ts is None:
            row = conn.execute(
                "SELECT session_id FROM sessions_meta WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                total_skipped += 1
                continue

        started_at = session_meta.get("timestamp", "")
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            # Remove old entries if force re-indexing or --since (to update with new messages)
            if force or since_ts is not None:
                conn.execute(
                    "DELETE FROM messages_fts WHERE session_id = ?", (session_id,)
                )
                conn.execute(
                    "DELETE FROM sessions_meta WHERE session_id = ?", (session_id,)
                )

            # Insert messages into FTS
            for msg in messages:
                conn.execute(
                    "INSERT INTO messages_fts (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                    (session_id, msg["role"], msg["content"], msg["timestamp"])
                )

            # Insert/replace meta
            conn.execute(
                """INSERT OR REPLACE INTO sessions_meta
                   (session_id, file_path, started_at, message_count, indexed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, filepath, started_at, len(messages), now_iso)
            )

            conn.commit()
            total_indexed += 1
            total_messages += len(messages)
            print(f"  ✅ {session_id[:8]}… — {len(messages)} messages")

        except sqlite3.Error as e:
            errors.append((session_id, str(e)))
            conn.rollback()
            print(f"  ❌ {session_id[:8]}… — DB error: {e}", file=sys.stderr)

    conn.close()

    print(f"\n📊 Indexing complete:")
    print(f"   Indexed : {total_indexed} sessions, {total_messages} messages")
    print(f"   Skipped : {total_skipped} (already indexed)")
    if errors:
        print(f"   Errors  : {len(errors)}")
        for sid, err in errors:
            print(f"     - {sid[:8]}…: {err}")


def cmd_search(query, limit=10):
    """Search messages using FTS5 and print results."""
    conn = get_db()

    # FTS5 MATCH query — wrap in quotes for phrase safety
    safe_query = query.replace('"', '""')

    try:
        rows = conn.execute(
            """SELECT session_id, role, content, timestamp,
                      rank
               FROM messages_fts
               WHERE messages_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (safe_query, limit)
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"Search error: {e}", file=sys.stderr)
        conn.close()
        return []

    conn.close()

    if not rows:
        print(f"No results for: {query!r}")
        return []

    print(f"\n🔍 Search: {query!r}  ({len(rows)} result{'s' if len(rows) != 1 else ''})\n")
    results = []
    for i, row in enumerate(rows, 1):
        snippet = row["content"][:200].replace("\n", " ")
        if len(row["content"]) > 200:
            snippet += "…"
        ts = row["timestamp"] or "unknown"
        score = round(row["rank"], 4) if row["rank"] else "n/a"
        print(f"[{i}] session={row['session_id'][:12]}…  role={row['role']}  ts={ts[:19]}  score={score}")
        print(f"    {snippet}")
        print()
        results.append(dict(row))

    return results


def cmd_stats():
    """Print DB statistics."""
    conn = get_db()

    session_count = conn.execute("SELECT COUNT(*) FROM sessions_meta").fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]

    print(f"\n📦 Session Index Stats")
    print(f"   DB path       : {DB_PATH}")
    print(f"   Sessions      : {session_count}")
    print(f"   Total messages: {msg_count}")

    if session_count > 0:
        oldest = conn.execute(
            "SELECT started_at FROM sessions_meta ORDER BY started_at ASC LIMIT 1"
        ).fetchone()[0]
        newest = conn.execute(
            "SELECT started_at FROM sessions_meta ORDER BY started_at DESC LIMIT 1"
        ).fetchone()[0]
        last_indexed = conn.execute(
            "SELECT MAX(indexed_at) FROM sessions_meta"
        ).fetchone()[0]
        print(f"   Oldest session: {oldest}")
        print(f"   Newest session: {newest}")
        print(f"   Last indexed  : {last_indexed}")

    role_counts = conn.execute(
        "SELECT role, COUNT(*) as cnt FROM messages_fts GROUP BY role"
    ).fetchall()
    if role_counts:
        print(f"   Role breakdown:")
        for row in role_counts:
            print(f"     {row['role']:12}: {row['cnt']}")

    conn.close()


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_since(value: str) -> float:
    """Parse a --since value into a Unix timestamp.

    Accepts:
      - "4h"   → 4 hours ago
      - "30m"  → 30 minutes ago
      - "2d"   → 2 days ago
      - ISO datetime string → parsed directly
    """
    import re
    now = datetime.now().timestamp()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(h|m|d)", value.strip().lower())
    if m:
        amount, unit = float(m.group(1)), m.group(2)
        seconds = {"h": 3600, "m": 60, "d": 86400}[unit]
        return now - amount * seconds
    # Try ISO parse
    try:
        dt = datetime.fromisoformat(value)
        return dt.timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid --since value: {value!r}. Use e.g. '4h', '30m', '2d', or ISO datetime."
        )


def main():
    parser = argparse.ArgumentParser(
        description="SQLite FTS5 session indexer for OpenClaw"
    )

    # Top-level --since flag (works standalone, triggers index with since filter)
    parser.add_argument(
        "--since",
        metavar="TIMESPEC",
        help="Re-index sessions modified after TIMESPEC (e.g. '4h', '30m', '2d'). "
             "Implies 'index' command with mtime filter.",
        default=None,
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("index", help="Index all sessions (skip already indexed)")
    subparsers.add_parser("reindex", help="Force re-index all sessions")
    subparsers.add_parser("stats", help="Show DB stats")

    search_p = subparsers.add_parser("search", help="Search messages")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")

    args = parser.parse_args()

    # --since used standalone (no subcommand) or with index
    if args.since is not None:
        try:
            since_ts = parse_since(args.since)
        except argparse.ArgumentTypeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        cmd_index(force=False, since_ts=since_ts)
        return

    if args.command == "index":
        cmd_index(force=False)
    elif args.command == "reindex":
        cmd_index(force=True)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "search":
        cmd_search(args.query, args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
cost_tracker.py — Per-Session Cost Tracking for Tania
Usage: python3 scripts/cost_tracker.py [track|report]
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path
import urllib.request
import urllib.error

# Load .env
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Config — auto-detect paths
def _detect_workspace_ct() -> str:
    if os.environ.get("OPENCLAW_WORKSPACE"):
        return os.environ["OPENCLAW_WORKSPACE"]
    if Path("/Users/mac/.openclaw/workspace").exists():
        return "/Users/mac/.openclaw/workspace"
    return str(Path(__file__).parent.parent)


def _detect_sessions_ct(workspace: str) -> str:
    if os.environ.get("OPENCLAW_SESSIONS"):
        return os.environ["OPENCLAW_SESSIONS"]
    candidates = [
        Path(workspace).parent / "agents/main/sessions",
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


WORKSPACE = _detect_workspace_ct()
SESSIONS_DIR = _detect_sessions_ct(WORKSPACE)
COST_FILE = f"{WORKSPACE}/memory/cost_tracking.json"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Keyword categories for task detection
CATEGORIES = {
    "carousel": ["carousel", "slide", "design", "nara", "konten", "instagram", "post"],
    "autofint": ["autofint", "finance", "keuangan", "wallet", "budget"],
    "coding": ["code", "script", "function", "bug", "fix", "deploy", "vps", "docker"],
    "memory": ["memory", "memori", "remember", "save", "query_memory"],
    "security": ["security", "audit", "firewall", "ssh", "vulnerability"],
    "automation": ["n8n", "workflow", "automation", "trigger", "webhook"],
    "heartbeat": ["heartbeat", "heartbeat_ok", "notion", "approval"],
    "client": ["ricky", "paradyse", "frx", "iqbal", "kenny", "turrima"],
}


def detect_category(content_str: str) -> str:
    """Detect task category from message content."""
    lower = content_str.lower()
    for cat, keywords in CATEGORIES.items():
        if any(k in lower for k in keywords):
            return cat
    return "general"


def extract_content_text(content) -> str:
    """Extract all text from message content (string or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "toolCall":
                    parts.append(item.get("name", ""))
                    args = item.get("arguments", {})
                    if isinstance(args, dict):
                        parts.append(str(args.get("command", "")))
                elif item.get("type") == "thinking":
                    parts.append(item.get("thinking", "")[:200])
        return " ".join(parts)
    return ""


def parse_session(filepath: str) -> dict:
    """Parse a JSONL session file and aggregate usage stats."""
    session_id = os.path.basename(filepath).replace(".jsonl", "")
    total = {
        "session_id": session_id,
        "filepath": filepath,
        "messages": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_write": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "categories": defaultdict(float),
        "first_timestamp": None,
        "last_timestamp": None,
        "model": None,
    }

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "message":
                continue

            msg = obj.get("message", {})
            if msg.get("role") != "assistant":
                continue

            usage = msg.get("usage", {})
            if not usage:
                continue

            # Timestamps
            ts = obj.get("timestamp")
            if ts:
                if total["first_timestamp"] is None:
                    total["first_timestamp"] = ts
                total["last_timestamp"] = ts

            # Model
            if not total["model"] and msg.get("model"):
                total["model"] = msg["model"]

            # Token counts
            inp = usage.get("input", 0)
            out = usage.get("output", 0)
            cr = usage.get("cacheRead", 0)
            cw = usage.get("cacheWrite", 0)
            cost_val = usage.get("cost", {}).get("total", 0)

            total["input_tokens"] += inp
            total["output_tokens"] += out
            total["cache_read"] += cr
            total["cache_write"] += cw
            total["total_tokens"] += usage.get("totalTokens", inp + out + cr + cw)
            total["cost_usd"] += cost_val
            total["messages"] += 1

            # Category detection
            content_str = extract_content_text(msg.get("content", ""))
            cat = detect_category(content_str)
            total["categories"][cat] += cost_val

    # Convert defaultdict to dict
    total["categories"] = dict(total["categories"])
    return total


def load_cost_db() -> dict:
    """Load the local cost tracking JSON file."""
    if os.path.exists(COST_FILE):
        try:
            with open(COST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sessions": {}, "last_updated": None}


def save_cost_db(db: dict):
    """Save cost tracking to local JSON."""
    db["last_updated"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(COST_FILE), exist_ok=True)
    with open(COST_FILE, "w") as f:
        json.dump(db, f, indent=2)


def save_to_supabase(session_data: dict) -> bool:
    """Try to save session cost to Supabase. Returns True if successful."""
    payload = {
        "session_id": session_data["session_id"],
        "messages": session_data["messages"],
        "input_tokens": session_data["input_tokens"],
        "output_tokens": session_data["output_tokens"],
        "cache_read": session_data["cache_read"],
        "cache_write": session_data["cache_write"],
        "total_tokens": session_data["total_tokens"],
        "cost_usd": round(session_data["cost_usd"], 6),
        "categories": json.dumps(session_data["categories"]),
        "model": session_data.get("model"),
        "first_timestamp": session_data.get("first_timestamp"),
        "last_timestamp": session_data.get("last_timestamp"),
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/session_costs",
        data=data,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201, 204)
    except urllib.error.HTTPError as e:
        # 409 = conflict (already exists) is fine
        if e.code in (409, 422):
            return True
        if e.code == 404:
            print(
                "  ⚠️  [Supabase] session_costs table not found in Supabase — "
                "run migration to create it: scripts/migrations/create_session_costs.sql"
            )
            return False
        print(f"  [Supabase] HTTP error {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as ex:
        print(f"  [Supabase] Error: {ex}")
        return False


def cmd_track():
    """Track all session files and save costs."""
    print("📊 Cost Tracker — Scanning sessions...\n")
    db = load_cost_db()
    sessions = db.get("sessions", {})

    # Find all .jsonl files (not .reset files)
    files = [
        f for f in glob.glob(f"{SESSIONS_DIR}/*.jsonl")
        if ".reset." not in f
    ]
    files.sort(key=os.path.getmtime)

    new_count = 0
    skip_count = 0

    for filepath in files:
        session_id = os.path.basename(filepath).replace(".jsonl", "")
        mtime = os.path.getmtime(filepath)

        # Skip if already tracked (by mtime check)
        if session_id in sessions:
            cached_mtime = sessions[session_id].get("_mtime", 0)
            if abs(cached_mtime - mtime) < 1:
                skip_count += 1
                continue

        print(f"  Parsing: {session_id[:8]}...")
        data = parse_session(filepath)
        data["_mtime"] = mtime

        if data["messages"] == 0:
            print(f"    → No usage data found, skipping.")
            continue

        # Try Supabase first
        supabase_ok = save_to_supabase(data)
        if supabase_ok:
            print(f"    → Saved to Supabase ✓")
        else:
            print(f"    → Supabase failed, saved locally.")

        sessions[session_id] = data
        new_count += 1

    db["sessions"] = sessions
    save_cost_db(db)

    print(f"\n✅ Done. Tracked {new_count} new session(s), skipped {skip_count} unchanged.")
    return db


def cmd_report():
    """Print weekly cost summary report."""
    # Run tracking first
    db = cmd_track()
    sessions = db.get("sessions", {})

    if not sessions:
        print("\n⚠️  No sessions tracked yet.")
        return

    print("\n" + "="*60)
    print("📋 WEEKLY COST SUMMARY — Tania Agent")
    print("="*60)

    # Weekly window
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    weekly = []
    all_time = []

    for sid, data in sessions.items():
        all_time.append(data)
        ts = data.get("last_timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt >= week_ago:
                    weekly.append(data)
            except Exception:
                pass

    def print_summary(label, items):
        if not items:
            print(f"\n{label}: No data")
            return
        total_cost = sum(d.get("cost_usd", 0) for d in items)
        total_tokens = sum(d.get("total_tokens", 0) for d in items)
        total_input = sum(d.get("input_tokens", 0) for d in items)
        total_output = sum(d.get("output_tokens", 0) for d in items)
        total_cache = sum(d.get("cache_read", 0) for d in items)
        total_msgs = sum(d.get("messages", 0) for d in items)

        # Category breakdown
        cat_costs = defaultdict(float)
        for d in items:
            for cat, cost in d.get("categories", {}).items():
                cat_costs[cat] += cost

        print(f"\n{label} ({len(items)} sessions, {total_msgs} messages):")
        print(f"  💰 Total Cost:     ${total_cost:.4f} USD")
        print(f"  🔢 Total Tokens:   {total_tokens:,}")
        print(f"     Input:          {total_input:,}")
        print(f"     Output:         {total_output:,}")
        print(f"     Cache Read:     {total_cache:,}")

        if cat_costs:
            print(f"\n  📂 Cost by Category:")
            for cat, cost in sorted(cat_costs.items(), key=lambda x: -x[1]):
                pct = (cost / total_cost * 100) if total_cost > 0 else 0
                print(f"     {cat:<15} ${cost:.4f}  ({pct:.1f}%)")

    print_summary("📅 This Week (7d)", weekly)
    print_summary("🗂  All Time", all_time)

    # Most expensive sessions
    expensive = sorted(all_time, key=lambda d: d.get("cost_usd", 0), reverse=True)[:3]
    if expensive:
        print(f"\n  💸 Top 3 Most Expensive Sessions:")
        for d in expensive:
            sid = d.get("session_id", "?")[:8]
            cost = d.get("cost_usd", 0)
            ts = d.get("last_timestamp", "unknown")[:10]
            print(f"     {sid}...  ${cost:.4f}  [{ts}]")

    print("\n" + "="*60)
    print(f"  Last updated: {db.get('last_updated', 'never')}")
    print(f"  Local file: {COST_FILE}")
    print("="*60 + "\n")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "track":
        cmd_track()
    elif mode == "report":
        cmd_report()
    else:
        print(f"Usage: python3 scripts/cost_tracker.py [track|report]")
        sys.exit(1)

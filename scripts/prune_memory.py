#!/usr/bin/env python3
"""
prune_memory.py — Find stale/outdated memories and report them for archiving
Dry-run only — does NOT modify or delete anything.

Criteria for pruning:
  1. Older than 90 days (configurable)
  2. Contains stale keywords: SELESAI, deprecated, v1, done, closed, etc.

Usage:
  python3 prune_memory.py                    # Default: 90 days + stale keywords
  python3 prune_memory.py --days 60          # Custom age threshold
  python3 prune_memory.py --scope core       # Only check core memories
  python3 prune_memory.py --no-age           # Only check stale keywords
  python3 prune_memory.py --no-keywords      # Only check age

Note: The 'archived' column does not exist in current schema.
      This script reports what SHOULD be archived — manual action required.
      To actually archive, you'd need to:
        1. Add 'archived boolean default false' column in Supabase
        2. Use the PATCH command shown in the output
"""

import sys
import json
import os
import urllib.request
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SERVICE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS = {
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey": SERVICE_KEY,
}

# Keywords that signal a stale/outdated memory
STALE_KEYWORDS = [
    # Indonesian completions
    "selesai", "sudah selesai", "sudah done", "sudah deployed", "sudah live",
    "sudah dikirim", "sudah dibayar", "sudah fix", "sudah fixed",
    # Version markers
    "v1", "v1.0", "v1.1", "v2 sudah", "versi lama",
    # Deprecated/closed
    "deprecated", "deprecated:", "obsolete", "tidak dipakai lagi", "sudah diganti",
    "replaced by", "diganti dengan", "pakai yang baru",
    # Project closure signals
    "project selesai", "sprint selesai", "milestone selesai",
    "done:", "[done]", "[selesai]", "[closed]", "[archived]",
    # Old/temp markers
    "sementara", "temporary", "temp:", "todo:", "fixme:",
]

def fetch(path):
    req = urllib.request.Request(f"{SUPABASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def parse_date(dt_str):
    """Parse ISO datetime string to timezone-aware datetime."""
    # Handle +00:00 or Z suffix
    dt_str = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        # Fallback: strip timezone info
        return datetime.fromisoformat(dt_str[:19]).replace(tzinfo=timezone.utc)

def check_stale_keywords(content: str) -> list[str]:
    """Return list of matched stale keywords in content."""
    content_lower = content.lower()
    return [kw for kw in STALE_KEYWORDS if kw in content_lower]

def main():
    parser = argparse.ArgumentParser(description="Find stale memories for archiving (dry-run)")
    parser.add_argument("--days", type=int, default=90, help="Age threshold in days (default: 90)")
    parser.add_argument("--scope", type=str, default=None, help="Filter by scope: core, channel, agent")
    parser.add_argument("--limit", type=int, default=1000, help="Max memories to scan (default: 1000)")
    parser.add_argument("--no-age", action="store_true", help="Skip age-based check")
    parser.add_argument("--no-keywords", action="store_true", help="Skip keyword-based check")
    args = parser.parse_args()

    scope_filter = f"&scope=eq.{args.scope}" if args.scope else ""
    path = f"/rest/v1/agent_memories?select=id,content,scope,agent_id,created_at,updated_at{scope_filter}&limit={args.limit}&order=created_at.asc"

    print(f"🔍 Prune Memory — DRY-RUN Report")
    print(f"   Age threshold: {args.days} days {'(skipped)' if args.no_age else ''}")
    print(f"   Stale keywords: {'(skipped)' if args.no_keywords else f'{len(STALE_KEYWORDS)} patterns'}")
    if args.scope:
        print(f"   Scope filter: {args.scope}")
    print()

    print("📥 Fetching memories...")
    memories = fetch(path)
    print(f"   Loaded {len(memories)} memories\n")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)

    old_memories = []
    stale_memories = []
    both_memories = []
    reported_ids = set()

    for m in memories:
        created = parse_date(m["created_at"])
        age_days = (now - created).days

        is_old = not args.no_age and (created < cutoff)
        matched_kw = [] if args.no_keywords else check_stale_keywords(m["content"])
        has_stale_kw = bool(matched_kw)

        if is_old and has_stale_kw:
            both_memories.append((m, age_days, matched_kw))
            reported_ids.add(m["id"])
        elif is_old:
            old_memories.append((m, age_days))
            reported_ids.add(m["id"])
        elif has_stale_kw:
            stale_memories.append((m, matched_kw))
            reported_ids.add(m["id"])

    # --- Report: Both criteria ---
    if both_memories:
        print(f"🔴 HIGH PRIORITY — Old + Stale Keywords ({len(both_memories)} memories)")
        print("=" * 70)
        for m, age, kws in both_memories:
            agent_label = m.get("agent_id") or "shared"
            print(f"\n  ID: {m['id']} | scope: {m['scope']} | agent: {agent_label} | age: {age}d")
            print(f"  Keywords: {', '.join(kws)}")
            print(f"  Content: {m['content'][:120]}{'...' if len(m['content']) > 120 else ''}")
        print()

    # --- Report: Old only ---
    if old_memories:
        print(f"🟡 OLD — Older than {args.days} days ({len(old_memories)} memories)")
        print("=" * 70)
        for m, age in old_memories[:20]:  # Cap display at 20
            agent_label = m.get("agent_id") or "shared"
            print(f"\n  ID: {m['id']} | scope: {m['scope']} | agent: {agent_label} | age: {age}d")
            print(f"  Content: {m['content'][:120]}{'...' if len(m['content']) > 120 else ''}")
        if len(old_memories) > 20:
            print(f"\n  ... and {len(old_memories) - 20} more (use --limit to see all)")
        print()

    # --- Report: Stale keywords only ---
    if stale_memories:
        print(f"🟠 STALE KEYWORDS — Possibly outdated ({len(stale_memories)} memories)")
        print("=" * 70)
        for m, kws in stale_memories:
            agent_label = m.get("agent_id") or "shared"
            print(f"\n  ID: {m['id']} | scope: {m['scope']} | agent: {agent_label} | created: {m['created_at'][:10]}")
            print(f"  Keywords: {', '.join(kws)}")
            print(f"  Content: {m['content'][:120]}{'...' if len(m['content']) > 120 else ''}")
        print()

    # --- Summary ---
    total_flagged = len(reported_ids)
    print("=" * 70)
    print(f"\n📊 Prune Summary (DRY-RUN)")
    print(f"   Total scanned:      {len(memories)}")
    print(f"   High priority:      {len(both_memories)} (old + stale keywords)")
    print(f"   Old only (>{args.days}d):  {len(old_memories)}")
    print(f"   Stale keywords:     {len(stale_memories)}")
    print(f"   Total flagged:      {total_flagged}")
    print(f"   Clean memories:     {len(memories) - total_flagged}")

    if total_flagged == 0:
        print(f"\n✅ No stale memories found! Memory is clean.")
    else:
        print(f"\n⛔ DRY-RUN: Nothing was modified.")
        print(f"\n💡 To archive these memories, first add 'archived' column to Supabase:")
        print(f"   ALTER TABLE agent_memories ADD COLUMN archived boolean DEFAULT false;")
        print(f"\n   Then use PATCH to mark as archived:")
        print(f"   curl -X PATCH '{SUPABASE_URL}/rest/v1/agent_memories?id=eq.<ID>'")
        print(f"        -H 'apikey: ...' -d '{{\"archived\": true}}'")
        print(f"\n   Or to delete:")
        print(f"   curl -X DELETE '{SUPABASE_URL}/rest/v1/agent_memories?id=eq.<ID>'")
        print(f"        -H 'apikey: ...'")

if __name__ == "__main__":
    main()

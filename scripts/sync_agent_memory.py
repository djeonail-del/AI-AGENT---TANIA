#!/usr/bin/env python3
"""
sync_agent_memory.py — Sync cross-agent memories to core scope
Reads memories from other agents (nara, lyra, rina) and promotes
high-value learnings to scope=core so all agents benefit.

Usage:
  python3 sync_agent_memory.py              # Dry-run: show what would be promoted
  python3 sync_agent_memory.py --promote    # Actually promote to core
  python3 sync_agent_memory.py --agent nara # Only sync from one agent
  python3 sync_agent_memory.py --days 7     # Only look at memories from last N days

Promotion criteria:
  - Memory belongs to a specific agent (agent_id = nara/lyra/rina)
  - Content contains cross-agent learnings (lessons, decisions, rules, preferences)
  - Not already in core (checked via exact content match)
"""

import sys
import json
import os
import urllib.request
import urllib.error
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_EMBED_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={GEMINI_API_KEY}"

HEADERS = {
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey": SERVICE_KEY,
    "Content-Type": "application/json",
}

# Known other agents to sync from
OTHER_AGENTS = ["nara", "lyra", "rina"]

# Keywords that signal a cross-agent worthy learning
LEARNING_KEYWORDS = [
    # Decision & rules
    "rule", "aturan", "jangan", "selalu", "harus", "wajib", "never", "always",
    # Lessons
    "lesson", "pelajaran", "ingat", "remember", "note", "catatan",
    # Workflow
    "workflow", "flow", "proses", "approval", "checklist",
    # Client/business context
    "djeon", "autofint", "client", "klien", "paradyse", "rototama",
    # Preference
    "prefer", "suka", "tidak suka", "reject", "approve",
    # Technical decisions
    "model", "gemini", "supabase", "n8n", "template",
]

def fetch(path):
    req = urllib.request.Request(f"{SUPABASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def post(path, data):
    req = urllib.request.Request(
        f"{SUPABASE_URL}{path}",
        data=json.dumps(data).encode(),
        headers={**HEADERS, "Prefer": "return=representation"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def patch(path, data):
    req = urllib.request.Request(
        f"{SUPABASE_URL}{path}",
        data=json.dumps(data).encode(),
        headers={**HEADERS, "Prefer": "return=minimal"},
        method="PATCH",
    )
    with urllib.request.urlopen(req) as r:
        return r.status

def get_embedding(text: str) -> list | None:
    """Generate embedding vector via Gemini gemini-embedding-001 (768 dim).
    Returns None on failure (embedding is optional — don't block promotion).
    """
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 768,
    }
    req = urllib.request.Request(
        GEMINI_EMBED_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result["embedding"]["values"]
    except Exception as e:
        print(f"      ⚠️  Embedding generation failed: {e}")
        return None

def is_cross_agent_worthy(content: str) -> tuple[bool, str]:
    """Check if memory content is worth promoting to core. Returns (worthy, reason)."""
    content_lower = content.lower()
    matched = [kw for kw in LEARNING_KEYWORDS if kw in content_lower]
    if matched:
        return True, f"contains keywords: {', '.join(matched[:3])}"
    return False, "no cross-agent signal"

def main():
    parser = argparse.ArgumentParser(description="Sync cross-agent memories to core scope")
    parser.add_argument("--promote", action="store_true", help="Actually promote (default: dry-run)")
    parser.add_argument("--agent", type=str, default=None, help="Only sync from specific agent")
    parser.add_argument("--days", type=int, default=None, help="Only look at memories from last N days")
    parser.add_argument("--limit", type=int, default=200, help="Max memories per agent to scan (default: 200)")
    args = parser.parse_args()

    agents_to_sync = [args.agent] if args.agent else OTHER_AGENTS
    mode = "PROMOTE" if args.promote else "DRY-RUN"
    print(f"🔄 Cross-Agent Memory Sync [{mode}]")
    print(f"   Agents: {', '.join(agents_to_sync)}")
    if args.days:
        print(f"   Period: last {args.days} days")
    print()

    # Load existing core memories (to avoid duplicates)
    print("📥 Loading existing core memories...")
    core_memories = fetch(f"/rest/v1/agent_memories?scope=eq.core&select=content&limit=1000")
    core_set = {m["content"].strip().lower() for m in core_memories}
    print(f"   Found {len(core_set)} existing core memories\n")

    total_scanned = 0
    total_candidates = 0
    total_promoted = 0
    all_candidates = []

    for agent in agents_to_sync:
        # Build date filter
        date_filter = ""
        if args.days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
            date_filter = f"&created_at=gte.{cutoff}"

        path = f"/rest/v1/agent_memories?agent_id=eq.{agent}&select=id,content,scope,created_at{date_filter}&limit={args.limit}&order=created_at.desc"
        
        try:
            memories = fetch(path)
        except Exception as e:
            print(f"  ❌ Error fetching {agent} memories: {e}")
            continue

        print(f"👤 Agent: {agent} — {len(memories)} memories")
        total_scanned += len(memories)

        agent_candidates = []
        for m in memories:
            # Skip if already in core
            if m["content"].strip().lower() in core_set:
                continue
            # Check if worthy
            worthy, reason = is_cross_agent_worthy(m["content"])
            if worthy:
                agent_candidates.append((m, reason))

        print(f"   → {len(agent_candidates)} candidate(s) for promotion")

        for m, reason in agent_candidates:
            total_candidates += 1
            all_candidates.append((agent, m, reason))
            print(f"   📌 [{reason}]")
            print(f"      {m['content'][:100]}{'...' if len(m['content']) > 100 else ''}")

            if args.promote:
                try:
                    result = post("/rest/v1/agent_memories", {
                        "content": m["content"],
                        "scope": "core",
                        "agent_id": None,  # Promote to shared — no agent_id
                        "tags": [f"synced_from_{agent}", "cross-agent"],
                    })
                    new_id = result[0]["id"]
                    print(f"      ✅ Promoted to core (new ID: {new_id})")
                    core_set.add(m["content"].strip().lower())  # Prevent re-promotion
                    total_promoted += 1

                    # Generate and store embedding for the newly promoted memory
                    emb = get_embedding(m["content"])
                    if emb:
                        try:
                            patch(f"/rest/v1/agent_memories?id=eq.{new_id}", {"embedding": emb})
                            print(f"      🧠 Embedding generated and stored")
                        except Exception as emb_err:
                            print(f"      ⚠️  Embedding stored failed: {emb_err}")
                    else:
                        print(f"      ⚠️  Embedding skipped (generation failed) — memory still promoted")
                except Exception as e:
                    print(f"      ❌ Promotion failed: {e}")
        print()

    # Summary
    print("=" * 60)
    print(f"📊 Summary [{mode}]")
    print(f"   Agents scanned:   {len(agents_to_sync)}")
    print(f"   Memories scanned: {total_scanned}")
    print(f"   Candidates found: {total_candidates}")
    if args.promote:
        print(f"   Promoted to core: {total_promoted}")
    else:
        print(f"   Would promote:    {total_candidates}")
        if total_candidates > 0:
            print(f"\n⚡ To actually promote, re-run with: --promote flag")

if __name__ == "__main__":
    main()

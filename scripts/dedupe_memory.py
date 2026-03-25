#!/usr/bin/env python3
"""
dedupe_memory.py — Find near-duplicate memories using cosine similarity
Usage:
  python3 dedupe_memory.py              # Find all duplicates (threshold=0.92)
  python3 dedupe_memory.py --threshold 0.85  # Custom threshold
  python3 dedupe_memory.py --scope core      # Only scan core memories

Dry-run only — does NOT delete anything.
"""

import sys
import json
import os
import urllib.request
import argparse
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

def fetch(path):
    req = urllib.request.Request(f"{SUPABASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x**2 for x in a) ** 0.5
    norm_b = sum(x**2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def parse_embedding(emb):
    if emb is None:
        return None
    if isinstance(emb, list):
        return emb
    if isinstance(emb, str):
        return [float(x) for x in emb.strip("[]").split(",")]
    return None

def main():
    parser = argparse.ArgumentParser(description="Find near-duplicate memories (dry-run)")
    parser.add_argument("--threshold", type=float, default=0.92, help="Cosine similarity threshold (default: 0.92)")
    parser.add_argument("--scope", type=str, default=None, help="Filter by scope: core, channel, agent")
    parser.add_argument("--limit", type=int, default=500, help="Max memories to scan (default: 500)")
    args = parser.parse_args()

    # Build query
    scope_filter = f"&scope=eq.{args.scope}" if args.scope else ""
    path = f"/rest/v1/agent_memories?embedding=not.is.null&select=id,content,scope,agent_id,created_at,embedding{scope_filter}&limit={args.limit}&order=created_at.asc"
    
    print(f"🔍 Fetching memories (limit={args.limit}{', scope='+args.scope if args.scope else ''})...")
    memories = fetch(path)
    print(f"   Loaded {len(memories)} memories with embeddings\n")

    if len(memories) < 2:
        print("Not enough memories to compare. Run: python3 semantic_memory.py embed")
        return

    # Pre-parse embeddings
    parsed = []
    for m in memories:
        emb = parse_embedding(m["embedding"])
        if emb:
            parsed.append({**m, "_emb": emb})

    print(f"   Comparing {len(parsed)} memories pairwise...")
    print(f"   Threshold: {args.threshold}\n")

    # Find duplicate pairs
    dup_pairs = []
    seen_ids = set()

    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            ma, mb = parsed[i], parsed[j]
            sim = cosine_similarity(ma["_emb"], mb["_emb"])
            if sim >= args.threshold:
                pair_key = (min(ma["id"], mb["id"]), max(ma["id"], mb["id"]))
                if pair_key not in seen_ids:
                    seen_ids.add(pair_key)
                    dup_pairs.append((sim, ma, mb))

    # Sort by similarity descending
    dup_pairs.sort(reverse=True, key=lambda x: x[0])

    if not dup_pairs:
        print(f"✅ No duplicates found above threshold {args.threshold}")
        return

    print(f"⚠️  Found {len(dup_pairs)} near-duplicate pair(s) (similarity ≥ {args.threshold}):\n")
    print("=" * 80)

    for idx, (sim, ma, mb) in enumerate(dup_pairs, 1):
        print(f"\n#{idx} — Similarity: {sim:.4f}")
        print(f"  [A] ID: {ma['id']} | scope: {ma['scope']} | agent: {ma.get('agent_id') or 'shared'} | created: {ma['created_at'][:10]}")
        print(f"      {ma['content'][:120]}{'...' if len(ma['content']) > 120 else ''}")
        print(f"  [B] ID: {mb['id']} | scope: {mb['scope']} | agent: {mb.get('agent_id') or 'shared'} | created: {mb['created_at'][:10]}")
        print(f"      {mb['content'][:120]}{'...' if len(mb['content']) > 120 else ''}")
        # Suggest which to keep (prefer core, prefer older)
        if ma["scope"] == "core" and mb["scope"] != "core":
            keep, remove = "A", "B"
        elif mb["scope"] == "core" and ma["scope"] != "core":
            keep, remove = "B", "A"
        elif ma["created_at"] <= mb["created_at"]:
            keep, remove = "A", "B"
        else:
            keep, remove = "B", "A"
        print(f"  💡 Suggest: keep [{keep}], review [{remove}]")

    print("\n" + "=" * 80)
    print(f"\n📊 Summary: {len(dup_pairs)} duplicate pairs found across {len(parsed)} memories")
    
    # Group clusters
    id_to_cluster = {}
    cluster_id = 0
    for _, ma, mb in dup_pairs:
        a_cluster = id_to_cluster.get(ma["id"])
        b_cluster = id_to_cluster.get(mb["id"])
        if a_cluster is None and b_cluster is None:
            id_to_cluster[ma["id"]] = cluster_id
            id_to_cluster[mb["id"]] = cluster_id
            cluster_id += 1
        elif a_cluster is not None and b_cluster is None:
            id_to_cluster[mb["id"]] = a_cluster
        elif b_cluster is not None and a_cluster is None:
            id_to_cluster[ma["id"]] = b_cluster

    unique_clusters = len(set(id_to_cluster.values()))
    unique_ids = len(id_to_cluster)
    print(f"   Affected memories: {unique_ids} across {unique_clusters} cluster(s)")
    print(f"\n⛔ DRY-RUN: Nothing was deleted. Review pairs above and manually remove duplicates.")
    print(f"   To delete: curl -X DELETE '{SUPABASE_URL}/rest/v1/agent_memories?id=eq.<ID>' -H 'apikey: ...'")

if __name__ == "__main__":
    main()

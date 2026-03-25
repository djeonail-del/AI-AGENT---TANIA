#!/usr/bin/env python3
"""
search_memory.py — Unified memory search across SQLite FTS5 + Supabase semantic memory.

Usage:
  python3 search_memory.py "query" [--limit N] [--fts-only] [--semantic-only]

Output:
  Combined, deduplicated results from both sources, ranked by relevance.
"""

import sys
import os
import argparse
import subprocess
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/Users/mac/.openclaw/workspace")


def search_fts(query, limit=5):
    """Search SQLite FTS5 via session_indexer.py and return structured results."""
    indexer = os.path.join(SCRIPT_DIR, "session_indexer.py")
    if not os.path.exists(indexer):
        return []

    try:
        # Import directly for cleaner integration
        sys.path.insert(0, SCRIPT_DIR)
        from session_indexer import cmd_search as _cmd_search, get_db

        import sqlite3
        db_path = os.path.join(WORKSPACE_DIR, "memory", "sessions.db")
        if not os.path.exists(db_path):
            return []

        conn = get_db(db_path)
        safe_query = query.replace('"', '""')
        try:
            rows = conn.execute(
                """SELECT session_id, role, content, timestamp, rank
                   FROM messages_fts
                   WHERE messages_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, limit)
            ).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return []

        conn.close()

        results = []
        for row in rows:
            results.append({
                "source": "fts5",
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"][:300],
                "timestamp": row["timestamp"],
                "score": row["rank"],
            })
        return results

    except Exception as e:
        print(f"  ⚠ FTS5 search error: {e}", file=sys.stderr)
        return []


def search_semantic(query, limit=5):
    """Search Supabase semantic memory via semantic_memory.py."""
    semantic_script = os.path.join(SCRIPT_DIR, "semantic_memory.py")
    if not os.path.exists(semantic_script):
        return []

    try:
        result = subprocess.run(
            [sys.executable, semantic_script, "search", query, "--limit", str(limit)],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=WORKSPACE_DIR,
        )
        output = result.stdout.strip()
        if not output:
            return []

        # Parse output — semantic_memory.py outputs JSON or plain text
        # Try JSON first
        try:
            data = json.loads(output)
            if isinstance(data, list):
                results = []
                for item in data:
                    results.append({
                        "source": "semantic",
                        "content": str(item.get("content", item.get("text", str(item))))[:300],
                        "score": item.get("similarity", item.get("score", 0)),
                        "metadata": item.get("metadata", {}),
                    })
                return results
        except json.JSONDecodeError:
            pass

        # Fallback: return raw text as single result block
        blocks = [b.strip() for b in output.split("\n\n") if b.strip()]
        return [
            {"source": "semantic", "content": b[:300], "score": None, "metadata": {}}
            for b in blocks[:limit]
        ]

    except subprocess.TimeoutExpired:
        print("  ⚠ Semantic search timed out", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  ⚠ Semantic search error: {e}", file=sys.stderr)
        return []


def deduplicate(results, threshold=0.85):
    """
    Remove near-duplicate results based on content similarity.
    Simple approach: skip results whose first 100 chars match an already-seen result.
    """
    seen = set()
    deduped = []
    for r in results:
        key = r["content"][:100].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def print_results(results, query):
    if not results:
        print(f"\nNo results found for: {query!r}")
        return

    print(f"\n🔍 Search: {query!r}  ({len(results)} result{'s' if len(results) != 1 else ''})\n")

    for i, r in enumerate(results, 1):
        source = r.get("source", "?")
        score = r.get("score")
        score_str = f"  score={round(score, 4)}" if score is not None else ""

        if source == "fts5":
            ts = r.get("timestamp", "")[:19]
            sid = r.get("session_id", "")[:12]
            role = r.get("role", "?")
            print(f"[{i}] 📄 FTS5 | session={sid}…  role={role}  ts={ts}{score_str}")
        else:
            meta = r.get("metadata", {})
            scope = meta.get("scope", "")
            print(f"[{i}] 🧠 Semantic | scope={scope}{score_str}")

        content = r.get("content", "").replace("\n", " ")
        print(f"    {content[:200]}{'…' if len(content) > 200 else ''}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Unified memory search (FTS5 + Semantic)")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=5, help="Max results per source (default: 5)")
    parser.add_argument("--fts-only", action="store_true", help="Only search SQLite FTS5")
    parser.add_argument("--semantic-only", action="store_true", help="Only search Supabase semantic")

    args = parser.parse_args()
    query = args.query
    limit = args.limit

    all_results = []

    if not args.semantic_only:
        print("🔎 Searching SQLite FTS5…", file=sys.stderr)
        fts_results = search_fts(query, limit)
        print(f"   → {len(fts_results)} FTS5 results", file=sys.stderr)
        all_results.extend(fts_results)

    if not args.fts_only:
        print("🔎 Searching Supabase semantic memory…", file=sys.stderr)
        sem_results = search_semantic(query, limit)
        print(f"   → {len(sem_results)} semantic results", file=sys.stderr)
        all_results.extend(sem_results)

    # Deduplicate
    all_results = deduplicate(all_results)

    print_results(all_results, query)


if __name__ == "__main__":
    main()

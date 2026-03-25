#!/usr/bin/env python3
"""
query_memory.py — Query agent memories dari Supabase
Usage: python3 query_memory.py [channel_id] [agent_id]
"""
import sys
import json
import os
import urllib.request
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

channel_id = sys.argv[1] if len(sys.argv) > 1 else None
agent_id = sys.argv[2] if len(sys.argv) > 2 else None

# Query core memories (shared semua)
def fetch(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

results = []

# 1. Core memories (semua agent, semua channel) — fetch ALL regardless of agent_id
core = fetch(f"{SUPABASE_URL}/rest/v1/agent_memories?scope=eq.core&select=content&order=created_at.asc")
results.extend([r['content'] for r in core])

# 2. Channel-specific (kalau ada channel_id)
if channel_id:
    chan = fetch(f"{SUPABASE_URL}/rest/v1/agent_memories?scope=eq.channel&channel_id=eq.{channel_id}&select=content&order=created_at.asc")
    results.extend([r['content'] for r in chan])

# 3. Agent-specific
if agent_id:
    agent = fetch(f"{SUPABASE_URL}/rest/v1/agent_memories?agent_id=eq.{agent_id}&select=content&order=created_at.asc")
    results.extend([r['content'] for r in agent])

print("\n".join(results))

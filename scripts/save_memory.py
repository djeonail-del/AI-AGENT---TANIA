#!/usr/bin/env python3
"""
save_memory.py — Simpan memory baru ke Supabase agent_memories
Usage:
  python3 save_memory.py "content memory" [scope] [channel_id] [agent_id]

Examples:
  # Core memory (shared semua agent)
  python3 save_memory.py "Djeon prefer konten dengan hook yang provokatif" core

  # Channel-specific (grup SMM)
  python3 save_memory.py "Di grup SMM kita diskusi strategi konten mingguan" channel -1003198983761

  # Agent-specific (hanya untuk Nara)
  python3 save_memory.py "Template carousel Lebaran berhasil viral, gunakan lagi" core "" nara

  # Update/lesson dari feedback
  python3 save_memory.py "Djeon reject carousel dengan background putih, selalu pakai dark" core
"""
import sys
import json
import os
import urllib.request
import urllib.error
from datetime import datetime
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

if len(sys.argv) < 2:
    print("Usage: python3 save_memory.py \"content\" [scope] [channel_id] [agent_id]")
    print("Scopes: core (default), channel, agent")
    sys.exit(1)

content    = sys.argv[1]
scope      = sys.argv[2] if len(sys.argv) > 2 else "core"
channel_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
agent_id   = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None

payload = {
    "content": content,
    "scope": scope,
}
if channel_id:
    payload["channel_id"] = channel_id
if agent_id:
    payload["agent_id"] = agent_id

data = json.dumps(payload).encode()
req = urllib.request.Request(
    f"{SUPABASE_URL}/rest/v1/agent_memories",
    data=data,
    headers={
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        print(f"✅ Memory saved!")
        print(f"   ID: {result[0]['id']}")
        print(f"   Scope: {scope}")
        print(f"   Content: {content[:80]}{'...' if len(content) > 80 else ''}")
except urllib.error.HTTPError as e:
    print(f"❌ Error: {e.read().decode()}")
    sys.exit(1)

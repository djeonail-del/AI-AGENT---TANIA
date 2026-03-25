# OpenClaw: From Basic to Hermes-Level Agent
_Dokumentasi oleh Tania 🌸 | Updated: 2026-03-26_

---

## 🟢 Level 1 — OpenClaw Basic (Out of the Box)

### Apa yang kamu dapat
- AI assistant via Telegram/Discord/WhatsApp/Signal
- 1 model (Claude/Gemini/dll)
- No memory — fresh start setiap session
- Skills bawaan (weather, web search, code, dll)
- Heartbeat: reply HEARTBEAT_OK saja

### Setup
```bash
npm install -g openclaw
openclaw onboard
openclaw gateway start
```

### Limitasi
- Tidak ingat percakapan sebelumnya
- Tidak ada konteks lintas session
- Single model, tidak ada fallback
- Tidak proaktif

---

## 🟡 Level 2 — Memory & Identity

### Tambahkan file identity ke workspace

**SOUL.md** — Karakter & kepribadian agent
```markdown
# SOUL.md
Be genuinely helpful, not performatively helpful.
Have opinions. Be resourceful before asking.
```

**IDENTITY.md** — Nama & avatar
```markdown
# IDENTITY.md
- Name: Tania
- Role: Personal Assistant
- Emoji: 🌸
```

**USER.md** — Profil user
```markdown
# USER.md
- Name: Djeon
- Location: Bali, Indonesia
- Preferences: Casual Indonesian, direct, no fluff
```

**MEMORY.md** — Long-term memory (tulis manual atau oleh agent)
```markdown
# MEMORY.md
- User prefers concise answers
- Active projects: AUTOFINT, Paradyse Homes
```

### Daily Notes
Buat folder `memory/` dan file harian:
```
memory/
  2026-03-26.md   ← raw log harian
  MEMORY.md       ← distilled long-term memory
```

---

## 🟠 Level 3 — Multi-Model Fallback

### Setup fallback models

```bash
# Cek model tersedia
openclaw models list --all

# Add fallback
openclaw models fallbacks add ollama/qwen3-vl:235b-cloud
openclaw models fallbacks add ollama/qwen3-vl:latest
openclaw models fallbacks add ollama/kimi-k2.5:cloud

# Cek hasil
openclaw models list
```

### Setup Ollama untuk model lokal & cloud
```bash
ollama pull qwen3-vl:latest          # 6.1GB, vision
ollama pull glm-ocr:latest           # 2.2GB, OCR
ollama pull kimi-k2.5:cloud          # cloud, gratis
ollama pull qwen3-vl:235b-cloud      # cloud, vision powerful
```

### Hasil akhir
```
Primary   → Claude Sonnet 4.6   (cloud, best quality)
Fallback1 → Qwen3-VL 235B cloud (cloud, vision)
Fallback2 → Qwen3-VL 7B local   (offline, vision)
Fallback3 → Kimi K2.5 cloud     (cloud, agentic)
```

### Ollama Vision Proxy (untuk enable vision di model cloud)
```bash
# Jalankan proxy di port 11435
python3 scripts/ollama_proxy.py &

# Set OpenClaw pakai proxy
# Edit openclaw.json:
# "models": { "providers": { "ollama": { "baseUrl": "http://127.0.0.1:11435", "api": "ollama", "models": [] } } }

# Auto-start via LaunchAgent
launchctl load ~/Library/LaunchAgents/ai.openclaw.ollama-proxy.plist
```

---

## 🔴 Level 4 — Live Context (Hermes-Style)

### Masalah yang diselesaikan
Session reset = kehilangan semua konteks percakapan

### Solusi: last-conversation.md

**Script:** `scripts/save_last_conversation.py`
- Baca JSONL session terbaru dari `~/.openclaw/agents/main/sessions/`
- Ambil 30 pesan terakhir (user + assistant)
- Simpan ke `memory/last-conversation.md`

**Kapan dijalankan:**
1. Di heartbeat (setiap 30 menit)
2. Saat pre-compaction hook
3. Manual kapanpun

**AGENTS.md rule:**
```markdown
## Session Startup
1. Read SOUL.md
2. Read USER.md  
3. Read memory/last-conversation.md  ← BARU
4. Read memory/YYYY-MM-DD.md
```

### Custom Workspace Hook (real-time)

**File:** `hooks/live-context/handler.ts`
```typescript
const handler = async (event: any) => {
  // Fire setiap message:sent, command:new, command:reset
  execSync('python3 scripts/save_last_conversation.py');
};
export default handler;
```

```bash
# Enable hook
openclaw hooks enable live-context
```

---

## 🔴 Level 5 — SQLite FTS5 Session Search

### Masalah yang diselesaikan
Tidak bisa ingat percakapan dari session lama (minggu/bulan lalu)

### Setup SQLite indexer

**Script:** `scripts/session_indexer.py`

```bash
# Index semua session
python3 scripts/session_indexer.py index

# Search percakapan lama
python3 scripts/session_indexer.py search "AUTOFINT carousel"

# Stats
python3 scripts/session_indexer.py stats
```

**Database:** `memory/sessions.db`
- FTS5 full-text search
- Index: session_id, role, content, timestamp
- Skip session yang sudah diindex (incremental)

### Unified Search

**Script:** `scripts/search_memory.py`
```bash
# Search gabungan: FTS5 + Supabase semantic
python3 scripts/search_memory.py "kimi vision setup"
python3 scripts/search_memory.py "AUTOFINT pricing" --fts-only
```

---

## 🔴 Level 6 — Supabase Semantic Memory

### Setup

```bash
# Save memory ke Supabase
python3 scripts/save_memory.py "Djeon suka response singkat" core

# Query memory
python3 scripts/query_memory.py

# Semantic search (lebih akurat)
python3 scripts/semantic_memory.py search "preferensi Djeon"

# Smart search (skip small talk)
python3 scripts/semantic_memory.py relevant "AUTOFINT,pricing"
```

### Memory scopes
- `core` — berlaku untuk semua session
- `channel` — khusus grup/channel tertentu
- `agent` — khusus agent ini

### Memory maintenance

```bash
# Hapus duplikat
python3 scripts/dedupe_memory.py

# Sinkronisasi antar agent
python3 scripts/sync_agent_memory.py --promote

# Prune memory lama (>90 hari)
python3 scripts/prune_memory.py
```

---

## 🔴 Level 7 — Proactive Agent (Heartbeat)

### HEARTBEAT.md
```markdown
## Priority Tasks

1. Jalankan save_last_conversation.py (selalu)
2. Cek Notion approval (Design Ready → review)
3. Anomaly detection (Supabase, VPS, Instagram)
4. Cek email/kalender kalau sudah > 4 jam
```

### Anomaly Detector

**Script:** `scripts/anomaly_detector.py`

Checks setiap heartbeat:
- ✅ Supabase connectivity
- ✅ Instagram posting gap (> 2 hari alert)
- ✅ Pending review carousel > 3 hari (cross-check Notion)
- ✅ VPS containers (nara/rina/lyra running?)

```bash
# Test dry-run
python3 scripts/anomaly_detector.py --dry-run
```

### Cost Tracker

```bash
python3 scripts/cost_tracker.py track   # track session ini
python3 scripts/cost_tracker.py report  # report per kategori
```

---

## 🔴 Level 8 — Multi-Agent Team

### Arsitektur

```
Djeon
  └─ Tania 🌸 (PA Pribadi, Mac mini, Telegram DM)
       ├─ Nara 🌿 (SMM AUTOFINT, VPS)
       ├─ Rina 🏢 (Client Manager, VPS)
       └─ Lyra ⚡ (Automation Engineer, VPS)
```

### Setup agent baru di VPS

```bash
# Di VPS
git clone https://github.com/openclaw/openclaw.git .agent-name
cd .agent-name
cp -r /root/.nara-openclaw/workspace ./workspace  # copy template

# Edit openclaw.json
{
  "agents": {
    "defaults": {
      "model": { "primary": "anthropic/claude-sonnet-4-6" },
      "workspace": "/root/.agent-name/workspace"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "TOKEN_DARI_BOTFATHER"
    }
  }
}

# Start
openclaw gateway start
```

### Inter-agent communication

```json
// openclaw.json
"agentToAgent": true,
"discord": {
  "allowBots": "mentions"
}
```

### Anti-loop rules (SOUL.md)
```markdown
1. Silent default terhadap sesama bot
2. Max 1 round-trip per conversation
3. Explicit handoff via @mention
4. Tahu kapan diam
```

---

## 📊 Summary: Level Comparison

| Level | Feature | Effort |
|-------|---------|--------|
| 1 | Basic OpenClaw | 30 menit |
| 2 | Memory & Identity | 1 jam |
| 3 | Multi-model fallback | 1 jam |
| 4 | Live context | 2 jam |
| 5 | SQLite session search | 1 jam |
| 6 | Supabase semantic memory | 2 jam |
| 7 | Proactive heartbeat | 1 jam |
| 8 | Multi-agent team | 4+ jam |

**Total: ~12 jam untuk full Hermes-level setup**

---

## 🛠 Scripts Index

| Script | Fungsi |
|--------|--------|
| `save_last_conversation.py` | Backup 30 pesan terakhir ke last-conversation.md |
| `session_indexer.py` | Index semua session ke SQLite FTS5 |
| `search_memory.py` | Unified search (FTS5 + Supabase) |
| `save_memory.py` | Save memory ke Supabase |
| `query_memory.py` | Query core memories |
| `semantic_memory.py` | Semantic search + smart gate |
| `anomaly_detector.py` | Health check + Telegram alerts |
| `cost_tracker.py` | Track biaya per session/kategori |
| `dedupe_memory.py` | Hapus duplikat memory Supabase |
| `sync_agent_memory.py` | Sinkronisasi memory antar agent |
| `prune_memory.py` | Prune memory lama/stale |
| `ollama_proxy.py` | Proxy Ollama untuk inject vision capability |
| `patch_kimi_models_json.py` | Patch models.json untuk vision |

---

## 🪝 Hooks Index

| Hook | Event | Fungsi |
|------|-------|--------|
| `live-context` | message:sent, command:new/reset | Save last-conversation.md real-time |
| `kimi-vision` | gateway:startup | Patch models.json untuk vision models |
| `session-memory` | command:new/reset | Save session memory (bundled) |
| `boot-md` | gateway:startup | Run BOOT.md (bundled) |

---

_Dibuat oleh Tania 🌸 berdasarkan pengalaman nyata setup Djeon AI Team, Maret 2026_

# HEARTBEAT.md

## 1. Save Last Conversation + Unified Timeline (Always Run First)

Jalankan ini di setiap heartbeat untuk backup percakapan terbaru:

```bash
cd /Users/mac/.openclaw/workspace && python3 scripts/save_last_conversation.py
```

Ini memastikan kalau session crash/overload, konteks percakapan tidak hilang (worst case kehilangan 30 menit terakhir).

Lalu build cross-channel unified timeline:

```bash
cd /Users/mac/.openclaw/workspace && python3 scripts/unified_timeline.py
```

Ini menyimpan timeline semua channel (Telegram DM + Discord) ke `memory/unified-timeline.md` — sehingga Tania tahu apa yang terjadi di semua channel dalam 24 jam terakhir.

---

## 2. Anomaly Detection (Run Every Heartbeat)

Run a quick health check:

```bash
cd /Users/mac/.openclaw/workspace && python3 scripts/anomaly_detector.py
```

Checks: Supabase connectivity · Instagram posting gap (> 3 days) · Pending review carousels > 3 days · VPS containers (nara/rina/lyra)

If anomalies found → auto-alerts sent to Djeon via Telegram. No action needed unless Djeon asks.

---

## 3. Notion Approval Check (Priority Task)

### Step 1 — Cek Notion
Query konten yang butuh review:
```bash
curl -s -X POST "https://api.notion.com/v1/databases/32b3d9d93ea180a1a68bc193e20b759b/query" \
  -H "Authorization: Bearer ${NOTION_KEY}" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"filter": {"property": "Status", "select": {"equals": "🎨 Design Ready"}}}'
```

Kalau ada entry → lanjut ke Step 2.

### Step 2 — Deep Research Topik

Sebelum review design, lakukan research dulu:
1. Baca caption + headline konten yang dibuat Nara
2. **Web search** topiknya dari minimal 3 sumber berbeda
3. Verifikasi fakta — angka, tanggal, nama, statistik
4. Cek apakah berita masih relevan / tidak outdated
5. Cek source URL yang Nara cantumkan di Notion (field Source URL)
6. Catat kalau ada yang perlu dikoreksi

### Step 3 — Review Design & Copy

Pakai checklist lengkap dari `sop/tania-approval-checklist.md`.

**Quick reference:**

**1. Akurasi (dari research):**
- [ ] Fakta akurat dan terverifikasi dari multiple sources
- [ ] Berita masih relevan / tidak outdated
- [ ] Tidak ada angka/statistik yang salah

**2. Design:**
- [ ] Text max 1 kalimat per elemen
- [ ] Box cyan bukan sebagai label kategori
- [ ] Tokoh/subjek prominent dan jelas
- [ ] Orientasi objek natural (HP tidak kebalik, dll)
- [ ] Dark background
- [ ] Font headline: ultra condensed bold (sesuai reference Ternakuang)
- [ ] Font di box biru/cyan: Inter SemiBold atau sejenis (BUKAN font yang sama dengan headline — harus ada kontras tipografi)
- [ ] Tidak ada AI artifacts major (teks garbled, wajah deformed, objek floating/tidak natural)

**3. Caption:**
- [ ] Ada hook di kalimat pertama
- [ ] Konten akurat, tidak misleading
- [ ] Soft CTA ke AUTOFINT (bukan hard sell)
- [ ] Tidak janji konten yang tidak ada di slide

**4. Hashtag:**
- [ ] Hanya 1 hashtag: `#autofintnews` atau `#autofinttips`

**5. Jadwal:**
- [ ] Tanggal masuk akal (tidak di masa lalu)
- [ ] Jam 11:00 WITA (berita) atau 15:00 WITA (tips) sebagai default

### Step 4 — Action

- **Semua ✅** → update status ke `✅ Design Approved`
- **Ada ❌** → update ke `❌ Rejected` + tulis feedback detail di Notes (termasuk koreksi fakta kalau ada)
- **Rejection > 2x** → notify Djeon (832986465) via Telegram

### Step 5 — Notify Djeon setelah Review

Setelah approve ATAU reject konten, **selalu notify Djeon via Telegram**:

```python
import urllib.request, json
action = "✅ APPROVED" # atau "❌ REJECTED"
konten = "nama konten"
alasan = "alasan singkat"
data = json.dumps({
    "chat_id": "832986465",
    "text": f"🌸 Tania review selesai\n{action}: {konten}\n{alasan}"
}).encode()
req = urllib.request.Request(
    "https://api.telegram.org/bot8729744179:AAGjUGVOBtwnBOVhO-WdSms1Yt1GUvYx7Y0/sendMessage",
    data=data, headers={"Content-Type": "application/json"}
)
urllib.request.urlopen(req)
```

---

Kalau tidak ada yang perlu dilakukan: **HEARTBEAT_OK**

---

## 4. Auto-Summarize Session (Always Run)

Setiap heartbeat, cek session status dan simpan summary kalau context > 40%:

```python
import subprocess, json, re
from datetime import datetime

# Cek context usage via session_status tool
# Kalau context > 40%, ringkas percakapan terakhir ke daily notes

today = datetime.now().strftime("%Y-%m-%d")
memory_file = f"/Users/mac/.openclaw/workspace/memory/{today}.md"

# Baca transcript session terbaru
import glob, os
session_dir = "/Users/mac/.openclaw/agents/main/sessions"
files = sorted(glob.glob(f"{session_dir}/*.jsonl"), key=os.path.getmtime, reverse=True)

if files:
    latest = files[0]
    messages = []
    with open(latest) as f:
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get('type') == 'message':
                    msg = obj.get('message', {})
                    role = msg.get('role', '')
                    if role in ('user', 'assistant'):
                        content = msg.get('content', '')
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get('type') == 'text':
                                    messages.append(f"[{role.upper()}]: {c['text'][:300]}")
            except:
                pass
    
    # Simpan 20 pesan terakhir ke memory kalau belum ada
    recent = "\n".join(messages[-20:])
    print(f"Session tracked: {len(messages)} messages")
```

**Aturan:** 
- Jika context < 40% → skip, lanjut ke task lain
- Jika context ≥ 40% → ringkas topik penting yang belum tersimpan ke `memory/YYYY-MM-DD.md`
- Jangan duplikasi — cek dulu apakah topik sudah ada di file memory hari ini

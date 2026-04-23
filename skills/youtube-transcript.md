# Skill: Ambil Transcript YouTube via TranscriptAPI

**Tanggal:** 2026-04-23
**Trigger:** User kirim link YouTube / minta transcript / minta ringkasan video

---

## Problem

YouTube tidak menyediakan transcript publik via API resmi gratis. Solusinya pakai layanan pihak ketiga `transcriptapi.com` yang sudah handle subtitle extraction + bahasa.

## Setup

API key disimpan di `.env` (sudah di-gitignore):

```bash
TRANSCRIPT_API_KEY=sk_xxx
TRANSCRIPT_API_BASE=https://transcriptapi.com/api/v2
```

Auth pakai header: `Authorization: Bearer <KEY>`.

## Endpoints

| Endpoint | Method | Credit | Use |
|----------|--------|--------|-----|
| `/youtube/transcript` | GET | 1 | Ambil transcript video |
| `/youtube/search` | GET | 1 | Search video/channel |
| `/youtube/channel/resolve` | GET | Free | @handle → channel ID |
| `/youtube/channel/search` | GET | 1 | Search dalam channel |
| `/youtube/channel/videos` | GET | 1/page | List upload channel |
| `/youtube/channel/latest` | GET | Free | 15 video terbaru (RSS) |
| `/youtube/playlist/videos` | GET | 1/page | List video playlist |

## Solution — Ambil Transcript

```bash
# Load env
set -a; source /home/user/AI-AGENT---TANIA/.env; set +a

# Pakai video_url (boleh full URL atau hanya video ID)
curl -s -X GET "${TRANSCRIPT_API_BASE}/youtube/transcript?video_url=dQw4w9WgXcQ" \
  -H "Authorization: Bearer ${TRANSCRIPT_API_KEY}"
```

## Contoh Search

```bash
curl -s -X GET "${TRANSCRIPT_API_BASE}/youtube/search?q=claude+code&type=video&limit=5" \
  -H "Authorization: Bearer ${TRANSCRIPT_API_KEY}"
```

## Notes

- Param utama transcript = `video_url` (bisa ID `dQw4w9WgXcQ` atau URL penuh `https://youtube.com/watch?v=...`)
- Channel videos & playlist videos pakai pattern `continuation` token untuk pagination
- Response berbentuk JSON — parse pakai `jq` atau Python
- Credit dihitung per request, cek dashboard untuk quota
- Kalau dapat 401 → cek API key, kalau 429 → kena rate limit

## Status

✅ Configured — 2026-04-23

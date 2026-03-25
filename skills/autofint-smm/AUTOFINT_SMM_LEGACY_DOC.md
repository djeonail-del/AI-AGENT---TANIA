# AUTOFINT SMM — Legacy System Documentation
_Diarsipkan: 2026-03-22 | Dibuat oleh: Tania 🌸_

> Dokumentasi lengkap sistem TypeScript sebelum migrasi ke OpenClaw AI Agent.

---

## 🏗️ Arsitektur Sistem

```
VPS Hostinger (212.85.27.223, Ubuntu 24.04)
├── Traefik (reverse proxy + SSL)
├── n8n (workflow automation — tidak dipakai untuk SMM)
├── WAHA (WhatsApp — tidak dipakai untuk SMM)
├── autofint-automation (TypeScript, port 3002) ← CORE SMM ENGINE
└── autofint-dashboard (Next.js 14, port 3001) ← REVIEW UI
    └── social.autofint.id
```

---

## 🔧 Automation Service (`/root/autofint-automation`)

### Stack
- Runtime: Node.js + TypeScript
- Framework: Express.js
- Cron: node-cron
- AI: @google/genai (Gemini 3.1 Pro text, Imagen 4 Ultra image)
- Storage: Supabase Storage (bucket: carousel-slides)
- DB: Supabase PostgreSQL

### Cron Schedule (WITA)
| Job | Waktu | Fungsi |
|-----|-------|--------|
| Scraper | 06:00 setiap hari | Ambil berita dari RSS + SerpAPI |
| Creator | 07:00 setiap hari | Generate carousel dari ideas |
| Notifier | 08:00 Senin & Kamis | Kirim notif review ke Telegram |
| Publisher | 11:00 setiap hari | Post ke Instagram via Repliz |

### Webhook Endpoints
| Method | Path | Fungsi |
|--------|------|--------|
| POST | /generate | Trigger generate carousel manual |
| POST | /research | Trigger scraping manual |
| POST | /approve | Approve carousel untuk publish |
| POST | /reject | Reject carousel |
| POST | /breaking-news | Generate breaking news carousel |
| POST | /revise-carousel | Revisi seluruh carousel |
| POST | /revise-slide | Revisi 1 slide spesifik |

### Source Files
```
src/
├── server.ts          — Express server entry point
├── scheduler.ts       — Cron job scheduler
├── jobs/
│   ├── scraper.ts     — RSS + SerpAPI news scraping
│   ├── creator.ts     — Carousel generation orchestrator
│   ├── notifier.ts    — Telegram review notifications
│   ├── publisher.ts   — Repliz Instagram publisher
│   └── researcher.ts  — Research job
├── lib/
│   ├── gemini.ts      — Gemini AI (text + image generation)
│   ├── storage.ts     — Supabase Storage upload
│   ├── supabase.ts    — Supabase client
│   ├── telegram.ts    — Telegram bot messaging
│   └── repliz.ts      — Repliz API (Instagram publisher)
└── webhooks/
    ├── approve.ts
    ├── reject.ts
    ├── generate.ts
    ├── research.ts
    ├── breaking.ts
    ├── revise-carousel.ts
    └── revise-slide.ts
```

---

## 🖥️ Dashboard (`/root/autofint-dashboard`)

### Stack
- Next.js 14, TypeScript, Tailwind CSS, shadcn/ui
- Real-time: Supabase Realtime subscriptions
- Mobile-first, bottom navigation

### Pages
| Route | Fungsi |
|-------|--------|
| / | War Room (overview status) |
| /review | Swipe review carousel (approve/reject) |
| /calendar | Notion-style content calendar |
| /ideas | Kelola ideas dari scraper |
| /analytics | Statistik posting |
| /settings | Config system |

### URL
- Production: https://social.autofint.id

---

## 🗄️ Database (Supabase)

### Project
- Name: autofint-carousel-factory
- URL: https://jppgtjiochtlxauwvbnu.supabase.co
- Region: Singapore

### Tables
| Table | Fungsi |
|-------|--------|
| `carousels` | Data carousel (status, scheduled_for, dll) |
| `slides` | Slide per carousel (image_url, headline, dll) |
| `ideas` | Ideas hasil scraping |
| `templates` | Template carousel per pillar |
| `config` | System configuration |
| `activity_logs` | Audit trail |

### Status Flow Carousel
```
generating → pending_review → approved → scheduled → published
                           ↘ rejected
```

### Pillar Schedule
| Hari | Pillar | Slides |
|------|--------|--------|
| Senin | Berita Ekonomi | 5 |
| Selasa | Tips Finance | 3 |
| Rabu | Tokoh & Quote | 2 |
| Kamis | Berita Ekonomi | 5 |
| Jumat | Lifestyle & Keuangan | 3 |
| Sabtu | Data & Fakta | 1 |
| Minggu | Tokoh & Quote | 2 |

---

## 🔑 Credentials

### Supabase
- URL: `https://jppgtjiochtlxauwvbnu.supabase.co`
- Anon Key: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcGd0amlvY2h0bHhhdXd2Ym51Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQxMTI1MjQsImV4cCI6MjA4OTY4ODUyNH0.2kCWsv2QZi_V0H8_MbryfpzB9WKH3eJANpcZ87iKiWU`
- Service Role Key: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcGd0amlvY2h0bHhhdXd2Ym51Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDExMjUyNCwiZXhwIjoyMDg5Njg4NTI0fQ.nwqShEJaUMmI_c4YEwH1PnBpfC1UfzV5-ZwKuIiW5TA`

### Repliz (Instagram Publisher)
- Account ID: `69b46950cb039db7d7db6c2f`
- User: `0735094494`
- Pass: `6e2xtJYOVYkHtPnJHQvFqSFp29bJfdWW`
- API: `https://api.repliz.com/public`

### Telegram Bot (SMM Notifier)
- Bot: @autofintsmmbot
- Token: `8567581942:AAGefvRE-5c0Hq62sOti1wMqX2WcYYpZABw`
- Chat ID Djeon: `832986465`

### Gemini
- API Key: `AIzaSyDBBKpczOBCfJaOmBvm_palb8fhYUP_G1Q`
- Text model: `gemini-3.1-pro-preview`
- Image model: `imagen-4.0-ultra-generate-001`

### SerpAPI
- Key: `b90b9d14fb7eb64dfadb6b014a3818081689a1c45ba9c7c6d0e350c1f8689493`

### Google Drive
- Folder ID: `1Fs4omUgqxLPuTLLdH1aPT3esyzTOJqnu`
- Service Account: `autofint-gdrive@autofint-482617.iam.gserviceaccount.com`

### Grid Reference (Ternakuang style)
- URL: `https://lh3.googleusercontent.com/d/1rHNxROD8Xpc1RdVVHjGOy65szgNFSkb4`

---

## 🎨 Image Prompt (Proven)

```
Font: Akkordeon Eleven for headline (ultra condensed, heavy, ALL CAPS)
Font: Sohne for subtitle
Colors: #00D4FF highlights, white text, #F97316 CTA only
Background: dark gradient, never flat black
Size: 1080x1350px (4:5 portrait)
Reference: Ternakuang grid (attach as reference image)
```

---

## 🐛 Known Issues (saat diarsipkan)

1. **Preview dashboard tidak muncul** — Next.js cache + Supabase domain belum di-whitelist di `remotePatterns`
2. **GDrive upload gagal** — Service Account tidak punya storage quota, butuh Shared Drive
3. **Slide duplikat headline** — Bug di creator.ts saat generate slide 3 series "Cara Hidup Hemat"
4. **Beberapa carousel belum regenerate** dengan grid reference Ternakuang baru

---

## 🔄 Alasan Migrasi ke OpenClaw Agent

- TypeScript terlalu rigid, tidak adaptif
- Butuh maintain kode untuk setiap perubahan
- Tidak bisa belajar dari feedback Djeon
- Ingin "karyawan AI" yang self-improving, bukan webapp statis

---

## 📦 Cara Restore (kalau dibutuhkan)

```bash
# SSH ke VPS
ssh root@212.85.27.223

# Clone/restore dari backup
# docker compose up -d
```

_Tania 🌸 | 2026-03-22_

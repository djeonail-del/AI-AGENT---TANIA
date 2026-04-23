# Skill: Trading Bot Deploy Runbook (Fase 1 MVP)

**Tanggal:** 2026-04-23
**Repo:** `trading-bot/` di workspace ini
**Status:** Fase 1 MVP, testnet-only

---

## Quick deploy (dari Mac Djeon ke VPS 212.85.27.223)

```bash
cd /Users/mac/.openclaw/workspace
# atau dari GitHub kalau sudah merged

# 1. Copy ke VPS
rsync -avz --exclude=__pycache__ --exclude=.env \
      --exclude='data/*.parquet' --exclude='db/*.db' \
      trading-bot/ root@212.85.27.223:/opt/tania-trading/

# 2. Copy .env terpisah (kredensial)
scp trading-bot/.env.example root@212.85.27.223:/opt/tania-trading/.env
ssh root@212.85.27.223 nano /opt/tania-trading/.env
# Fill BINANCE_TESTNET_API_KEY + SECRET dari .env kita sendiri

# 3. Install + start
ssh root@212.85.27.223 '
  cd /opt/tania-trading &&
  bash deploy/install.sh &&
  docker compose up -d
'

# 4. Tail logs
ssh root@212.85.27.223 'cd /opt/tania-trading && docker compose logs -f tania-bot'
```

## Monitor checklist

| Check | Command |
|-------|---------|
| Services up? | `docker compose ps` |
| Bot heartbeat | `docker compose logs --tail 20 tania-bot` |
| Research progress | `docker compose logs --tail 20 tania-research` |
| Recent trades | `docker compose exec tania-bot python -c "import sqlite3,sys; c=sqlite3.connect('/app/db/trades.db'); c.row_factory=sqlite3.Row; [print(dict(r)) for r in c.execute('SELECT * FROM orders ORDER BY ts DESC LIMIT 5')]"` |
| Current equity | `docker compose exec tania-bot python -c "import sqlite3; c=sqlite3.connect('/app/db/trades.db'); r=c.execute('SELECT * FROM equity_curve ORDER BY ts DESC LIMIT 1').fetchone(); print(r)"` |
| Research candidates that passed guards | `docker compose exec tania-bot python -c "import sqlite3,json; c=sqlite3.connect('/app/db/trades.db'); c.row_factory=sqlite3.Row; [print(dict(r)) for r in c.execute('SELECT id, generation, params_json, val_sharpe, win_rate FROM candidates WHERE passed_guards=1 ORDER BY val_sharpe DESC LIMIT 5')]"` |

## Integrasi dengan Tania

Tambah ke `HEARTBEAT.md`:

```bash
# Check trading bot status (kalau ada)
ssh root@212.85.27.223 'docker compose -f /opt/tania-trading/docker-compose.yml ps' 2>/dev/null
```

Atau bikin script `scripts/trading_health.py` yang SSH ke VPS, query DB, masuk ke `memory/cross-channel-inbox.md` kalau ada anomali.

## Emergency close

```bash
ssh root@212.85.27.223 'cd /opt/tania-trading && docker compose run --rm tania-bot python emergency_close.py'
```

## Known gotchas

1. **Testnet data history pendek** (~7 hari). Research pakai production fapi (public, no auth) untuk data historis. Di region yang kena 451 geo-block, fallback otomatis ke testnet (kualitas backtest menurun).
2. **Testnet recvWindow** kadang strict — pastikan VPS clock sync (`timedatectl status`).
3. **Baseline RSI strategy conservative** — di market trending bisa 0 trade/hari. Itu normal, research loop bakal explore looser variants.
4. **Drawdown guard 5%/24h** — kalau kena → bot auto-pause. Reset manual via `set_pause(False)`.
5. **Fee bleed** — kalau strategy 100+ trade/hari, fee 0.04% × 2 (open+close) = 8%/hari kotor. Guard `fee_ratio > 30%` akan reject.

## Naik ke Fase 2 — checklist

- [ ] Bot + research running 3+ hari uptime 100%
- [ ] Minimal 1 candidate passing guards di SQLite
- [ ] Equity curve tersimpan, kill switch belum tereksekusi
- [ ] Telegram alert (kalau sudah setup) pernah terbaca Tania
- [ ] Manual smoke test emergency_close works

Kalau semua ✅ → bikin `check_and_promote.py` cron + SOP review.

## Status

✅ Deploy pack complete — 2026-04-23

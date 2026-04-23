# Tania Trading Bot — Fase 1 MVP

Autonomous trading bot for Binance USDⓈ-M Futures testnet.
Runs 24/7 in Docker. Pattern: Karpathy's autoresearch adapted to trading.

## Shared account with Zara (important!)

Tania dan Zara pakai **akun Binance testnet yang sama** tapi pair berbeda:

| Bot | Symbol | Virtual capital |
|-----|--------|-----------------|
| Zara (BTCUSDT) | `BTCUSDT` | (Zara's own tracking) |
| **Tania (this bot)** | `ETHUSDT` | `$5000` (env `BOT_VIRTUAL_CAPITAL`) |

Key isolation features (in `bot.py`):
- **`BOT_SYMBOL`** env var — trade only this pair
- **Virtual equity** = `BOT_VIRTUAL_CAPITAL + realized_pnl(SYMBOL) + commission(SYMBOL) + unrealized_pnl`
- **Position sizing** uses virtual equity, not account balance → Tania can't over-allocate into Zara's share
- **Kill switch** scopes to virtual equity drawdown → Zara's PnL can't trigger Tania's pause
- **Realized PnL source** = Binance `/fapi/v1/income?symbol=ETHUSDT&incomeType=REALIZED_PNL` (authoritative, filtered by symbol)

## What's in this repo

```
trading-bot/
├── prepare.py           READ-ONLY: data loader + backtest engine + safety guards
├── strategy.py          baseline RSI + EMA (research agent will evolve this)
├── bot.py               live trading loop (Champion)
├── research.py          autoresearch loop (random search, Fase 1 MVP)
├── emergency_close.py   panic button
├── program.md           rules for research agent
├── db/schema.sql        SQLite tables
├── Dockerfile
├── docker-compose.yml   two services: tania-bot + tania-research
├── requirements.txt
└── deploy/install.sh    VPS one-shot installer
```

## What it does (Fase 1)

1. **tania-bot container**: polls BTCUSDT 5m kline every 30s, runs strategy, places orders on Binance testnet
2. **tania-research container**: in parallel, generates strategy variants + backtests against 15 months of history, saves candidates to SQLite
3. Both log to shared SQLite at `db/trades.db`

Fase 1 **does NOT** auto-promote candidates to live — that's Fase 2 after manual review.

## Safety rails (built-in)

- **Leverage cap**: 2x (env-configurable)
- **Position size**: 10% equity per trade
- **Stop loss**: -1%, Take profit: +2%
- **Kill switch**: auto-pause if 24h drawdown > -5%
- **Idempotent orders**: every order has `newClientOrderId = tania-<uuid>`
- **Reduce-only** on all closes
- **Error cascade**: auto-pause after 10 consecutive loop errors

## Deploy to VPS (from Mac / local)

```bash
# 1. Copy files to VPS (replace IP with yours)
rsync -avz --exclude=__pycache__ --exclude=.env --exclude=data --exclude=db \
  trading-bot/ root@212.85.27.223:/opt/tania-trading/

# 2. SSH and create .env
ssh root@212.85.27.223
cd /opt/tania-trading
cp .env.example .env
nano .env    # paste BINANCE_TESTNET_API_KEY and SECRET

# 3. Run installer (one-time)
bash deploy/install.sh

# 4. Start the bot + research
docker compose up -d

# 5. Watch it work
docker compose logs -f tania-bot
```

## Daily operations

```bash
# Status
docker compose ps
docker compose logs --tail 50 tania-bot

# Query database
docker compose exec tania-bot python -c "
import sqlite3
c = sqlite3.connect('/app/db/trades.db')
c.row_factory = sqlite3.Row
# Recent trades
for r in c.execute('SELECT * FROM orders ORDER BY ts DESC LIMIT 10'):
    print(dict(r))
# Equity now
row = c.execute('SELECT * FROM equity_curve ORDER BY ts DESC LIMIT 1').fetchone()
print('equity:', dict(row) if row else None)
"

# Emergency close everything
docker compose run --rm tania-bot python emergency_close.py

# Restart (e.g. after .env change)
docker compose down && docker compose up -d

# Review research candidates
docker compose exec tania-bot python -c "
import sqlite3, json
c = sqlite3.connect('/app/db/trades.db')
c.row_factory = sqlite3.Row
for r in c.execute('SELECT * FROM candidates WHERE passed_guards=1 ORDER BY val_sharpe DESC LIMIT 10'):
    d = dict(r)
    d['params'] = json.loads(d['params_json'])
    print(d)
"
```

## Kill the bot manually (hard stop)

```bash
docker compose stop tania-bot
# Or fully:
docker compose down
# Then close Binance positions via web UI if any remain
```

## Files that never change (safety)

- `prepare.py` — contains the metric (val_sharpe) + guards. If modified, every backtest becomes unreliable.
- `db/schema.sql` — modify only via migration (not supported in Fase 1)
- `bot.py` — the execution engine. Bug here = lost money.

## Files the research agent CAN modify

- `strategy.py` — entire contents, as long as `Strategy` class interface is preserved.

## Fase roadmap (agar jelas kapan boleh naik level)

| Fase | Gate untuk lanjut | Durasi target |
|------|-------------------|---------------|
| Fase 1 (sekarang) | Bot + research running 3+ hari tanpa crash di testnet | ~1 minggu |
| Fase 2 | Minimal 1 strategi hasil research lolos guard & manual review | ~1-2 minggu |
| Fase 3 | Auto-promote aktif, 30 hari clean di testnet | ~1 bulan |
| Fase 4 | Live dengan modal $50-100 | ongoing |

**Jangan skip fase.** Ini yang bikin video author kehilangan $500.

## Ground truth references

- `skills/autoresearch-pattern.md` — pola Karpathy yang kita adaptasi
- `skills/binance-derivatives-api.md` — doc Binance API lengkap

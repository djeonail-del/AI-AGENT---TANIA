# program.md — Rules for the Research Agent

This document is the skill spec for the autonomous research loop.
It describes **what** the agent optimizes for and **what** is off-limits.

## Goal

Find a trading strategy for BTCUSDT 5m perpetual that beats the current champion
on the validation slice of historical data, subject to safety guards.

Metric: **val_sharpe** (annualized Sharpe ratio on 90-day held-out data). Higher is better.

## Scope of edits

You MAY modify:
- `strategy.py` (entire file, as long as it exposes a `Strategy` class with the interface below)
- Add helper functions inside `strategy.py`

You MUST NOT modify:
- `prepare.py` (data loader, backtest engine, guards, metric — the ground truth)
- `bot.py` (live execution engine)
- `db/schema.sql`

You MUST NOT:
- Install new Python packages
- Touch the Binance API directly from strategy code
- Reference future data (look-ahead bias)
- Use train data to tune on val data

## Strategy interface

```python
class Strategy:
    def __init__(self, **params): ...
    def params(self) -> dict: ...  # return all tunable params, keyed by name
    def on_candle(self, df: pandas.DataFrame) -> str:
        # df has columns: open_time, open, high, low, close, volume
        # df is sorted ascending; df.iloc[-1] is the most recent CLOSED candle
        # return "LONG" | "SHORT" | "NOOP"
        ...
```

## Safety guards (defined in `prepare.check_guards`)

A candidate must pass ALL to be considered for promotion:

| Guard | Threshold | Rationale |
|-------|-----------|-----------|
| `num_trades >= 30` | Min sample | Smaller = noise |
| `sharpe <= 3.0` | Too high = suspect | Look-ahead bias |
| `sharpe >= 0.5` | Too low | Not worth deploying |
| `max_drawdown <= 0.15` | 15% | Risk cap |
| `win_rate <= 0.80` | | >80% usually = look-ahead |
| `win_rate >= 0.30` (unless sharpe ≥ 1.0) | | Sanity |
| `fee_ratio <= 0.30` | Fee bleed | Overtrading kills |
| `total_return <= 500%` | | Anything more = suspect |

## Experiment loop (implemented in `research.py`)

```
while True:
    params = mutate(champion) or random_params()
    train_res = backtest(strategy(**params), train_data)
    if not guards(train_res).passed:
        log failure, continue
    val_res = backtest(strategy(**params), val_data)  # blind holdout
    if guards(val_res).passed and val_res.sharpe > champion.val_sharpe:
        save as candidate (awaiting promotion)
    log, sleep 1s
```

## Promotion rules (implemented in `check_and_promote.py` cron)

Candidate → Champion if ALL:
- `val_sharpe > champion.val_sharpe * 1.2`
- Passes all guards
- Not promoted within last 1 hour (anti-thrashing)

## Auto-rollback

New champion is auto-demoted if within 24h of promotion:
- Realized drawdown >3% on LIVE account, OR
- 5 consecutive losing trades, OR
- Error rate >5% of requests

## What this is NOT

- Not a guarantee of profit. Backtest ≠ live.
- Not a substitute for human judgment. Weekly review by Djeon is expected.
- Not tested for regime change (2024 crypto = different from 2020). Re-train continually.

## When to escalate to human

Stop the loop and alert via Telegram if:
- No candidate passes guards for 24h straight (regime shift?)
- Champion's live P&L deviates >40% from its backtest prediction (model drift)
- Bot hits 10 consecutive errors (infrastructure issue)

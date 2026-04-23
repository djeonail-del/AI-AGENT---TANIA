"""
prepare.py — READ-ONLY infrastructure layer.

This file contains:
- Binance kline data loader (REST, cached)
- BacktestEngine with realistic fee simulation
- Safety guards (look-ahead, overfitting, fee bleed)
- Metric calculations (Sharpe, max drawdown, win rate)

The autoresearch agent MUST NOT modify this file. It is the ground truth.
"""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlencode

import httpx
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Fixed constants — DO NOT CHANGE
# ---------------------------------------------------------------------------

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Binance USDⓈ-M taker/maker fees (live is 0.04% / 0.02%; testnet identical)
TAKER_FEE = 0.0004
MAKER_FEE = 0.0002

# Walk-forward split: train on older data, validate on newer (never seen during search)
TRAIN_DAYS = 365        # 1 year of training data
VALIDATION_DAYS = 90    # 3 months held out

# Minimum sample size for a backtest result to be trusted
MIN_TRADES_BACKTEST = 30


# ---------------------------------------------------------------------------
# Binance REST client (minimal — for data only, not trading)
# ---------------------------------------------------------------------------

def get_rest_base() -> str:
    """Data source for backtest / research.

    Prefers production fapi (longest history, public data). Some regions are
    geo-blocked with HTTP 451 — fallback to testnet base then.
    Override explicitly via env: HISTORICAL_DATA_BASE.
    """
    override = os.environ.get("HISTORICAL_DATA_BASE")
    if override:
        return override
    return "https://fapi.binance.com"


def _sign(query: str, secret: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


async def fetch_klines(
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 1500,
) -> pd.DataFrame:
    """Fetch klines from Binance REST. No auth needed for market data.

    Retries on 429/5xx with exponential backoff.
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    bases_to_try = [get_rest_base()]
    # Geo-block fallback: if production blocks us, try testnet (shorter history but ok)
    if "testnet" not in bases_to_try[0]:
        bases_to_try.append("https://testnet.binancefuture.com")

    last_err: str | Exception = "unknown"
    rows = None
    for base in bases_to_try:
        url = f"{base}/fapi/v1/klines"
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(url, params=params)
                    if r.status_code == 451:
                        last_err = f"451 (geo-blocked on {base})"
                        break  # try next base
                    if r.status_code in (429, 500, 502, 503, 504):
                        last_err = f"HTTP {r.status_code}: {r.text[:150]}"
                        await asyncio.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    rows = r.json()
                    break
            except (httpx.HTTPError, httpx.ReadTimeout) as e:
                last_err = e
                await asyncio.sleep(2 ** attempt)
        if rows is not None:
            break
    if rows is None:
        raise RuntimeError(f"fetch_klines failed after retries: {last_err}")

    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "_ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]]


async def load_historical(days: int = 365 + 90, cache: bool = True) -> pd.DataFrame:
    """Fetch and cache ~15 months of 5m klines for BTCUSDT.

    Returns ~130k candles. Cached as parquet for fast reload.
    """
    cache_path = DATA_DIR / f"{SYMBOL}_{INTERVAL}_{days}d.parquet"
    if cache and cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 24:
            return pd.read_parquet(cache_path)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    all_chunks: list[pd.DataFrame] = []
    cur = start_ms
    while cur < end_ms:
        chunk = await fetch_klines(SYMBOL, INTERVAL, start_ms=cur, limit=1500)
        if chunk.empty:
            break
        all_chunks.append(chunk)
        last_ts = int(chunk["open_time"].iloc[-1].timestamp() * 1000)
        if last_ts <= cur:
            break
        cur = last_ts + 1

    df = pd.concat(all_chunks, ignore_index=True).drop_duplicates("open_time")
    df = df.sort_values("open_time").reset_index(drop=True)
    if cache:
        df.to_parquet(cache_path)
    return df


def walk_forward_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into (train, validation). Validation is the last N days."""
    cutoff = df["open_time"].max() - pd.Timedelta(days=VALIDATION_DAYS)
    train = df[df["open_time"] <= cutoff].reset_index(drop=True)
    val = df[df["open_time"] > cutoff].reset_index(drop=True)
    return train, val


# ---------------------------------------------------------------------------
# Trade & backtest primitives
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str          # "LONG" or "SHORT"
    entry_price: float
    exit_price: float
    qty: float
    fee_paid: float
    pnl_gross: float
    pnl_net: float
    exit_reason: str   # "stop_loss", "take_profit", "signal_flip", "end_of_data"


@dataclass
class BacktestResult:
    start: pd.Timestamp
    end: pd.Timestamp
    num_trades: int
    win_rate: float
    sharpe: float
    max_drawdown: float
    total_return_pct: float
    fee_ratio: float       # fees / gross_profit
    final_equity: float
    trades: list[Trade]

    def summary(self) -> dict:
        d = asdict(self)
        d["trades"] = len(self.trades)
        d["start"] = str(self.start)
        d["end"] = str(self.end)
        return d


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    strategy,               # object with .on_candle(window) -> signal
    initial_equity: float = 10000.0,
    position_size_pct: float = 0.10,
    leverage: float = 2.0,
    stop_loss_pct: float = 0.01,
    take_profit_pct: float = 0.02,
    fee_taker: float = TAKER_FEE,
) -> BacktestResult:
    """Minimal event-driven backtest. 5m bar close only (no intrabar fills).

    - One position at a time (no pyramiding).
    - Entry at next bar open (no look-ahead).
    - Exit on stop-loss, take-profit, or signal flip.
    """
    if len(df) < 100:
        raise ValueError("Not enough data for backtest")

    equity = initial_equity
    equity_curve: list[float] = [equity]
    trades: list[Trade] = []

    position = None  # dict or None

    # Strategy needs some lookback — skip first 100 bars
    for i in range(100, len(df) - 1):
        window = df.iloc[: i + 1].copy()
        bar = df.iloc[i]
        next_bar = df.iloc[i + 1]

        # --- Exit logic for existing position ---
        if position is not None:
            side = position["side"]
            entry = position["entry_price"]
            qty = position["qty"]

            high = bar["high"]
            low = bar["low"]

            exit_price = None
            exit_reason = None

            if side == "LONG":
                stop = entry * (1 - stop_loss_pct)
                tp = entry * (1 + take_profit_pct)
                if low <= stop:
                    exit_price = stop
                    exit_reason = "stop_loss"
                elif high >= tp:
                    exit_price = tp
                    exit_reason = "take_profit"
            else:  # SHORT
                stop = entry * (1 + stop_loss_pct)
                tp = entry * (1 - take_profit_pct)
                if high >= stop:
                    exit_price = stop
                    exit_reason = "stop_loss"
                elif low <= tp:
                    exit_price = tp
                    exit_reason = "take_profit"

            if exit_price is not None:
                pnl_gross = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
                fee = (entry * qty + exit_price * qty) * fee_taker
                pnl_net = pnl_gross - fee
                equity += pnl_net
                trades.append(Trade(
                    entry_time=position["entry_time"],
                    exit_time=bar["open_time"],
                    side=side,
                    entry_price=entry,
                    exit_price=exit_price,
                    qty=qty,
                    fee_paid=fee,
                    pnl_gross=pnl_gross,
                    pnl_net=pnl_net,
                    exit_reason=exit_reason,
                ))
                position = None

        # --- Signal check (if no open position) ---
        signal = strategy.on_candle(window)

        if position is None and signal in ("LONG", "SHORT"):
            # Enter at next bar open (no look-ahead)
            entry_price = next_bar["open"]
            notional = equity * position_size_pct * leverage
            qty = notional / entry_price
            position = {
                "side": signal,
                "entry_price": entry_price,
                "qty": qty,
                "entry_time": next_bar["open_time"],
            }

        elif position is not None and signal in ("LONG", "SHORT") and signal != position["side"]:
            # Signal flip — close and reverse
            exit_price = next_bar["open"]
            entry = position["entry_price"]
            side = position["side"]
            qty = position["qty"]
            pnl_gross = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
            fee = (entry * qty + exit_price * qty) * fee_taker
            pnl_net = pnl_gross - fee
            equity += pnl_net
            trades.append(Trade(
                entry_time=position["entry_time"],
                exit_time=next_bar["open_time"],
                side=side,
                entry_price=entry,
                exit_price=exit_price,
                qty=qty,
                fee_paid=fee,
                pnl_gross=pnl_gross,
                pnl_net=pnl_net,
                exit_reason="signal_flip",
            ))
            position = None
            # Immediately enter opposite
            notional = equity * position_size_pct * leverage
            qty = notional / exit_price
            position = {
                "side": signal,
                "entry_price": exit_price,
                "qty": qty,
                "entry_time": next_bar["open_time"],
            }

        equity_curve.append(equity)

    # Close any remaining position at last close
    if position is not None:
        last = df.iloc[-1]
        exit_price = last["close"]
        entry = position["entry_price"]
        side = position["side"]
        qty = position["qty"]
        pnl_gross = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
        fee = (entry * qty + exit_price * qty) * fee_taker
        pnl_net = pnl_gross - fee
        equity += pnl_net
        trades.append(Trade(
            entry_time=position["entry_time"],
            exit_time=last["open_time"],
            side=side,
            entry_price=entry,
            exit_price=exit_price,
            qty=qty,
            fee_paid=fee,
            pnl_gross=pnl_gross,
            pnl_net=pnl_net,
            exit_reason="end_of_data",
        ))

    eq = np.array(equity_curve)
    returns = np.diff(eq) / eq[:-1]

    if len(trades) == 0 or returns.std() == 0:
        sharpe = 0.0
    else:
        # Annualized Sharpe. 5m bars => 288 per day => 288 * 365 per year.
        sharpe = returns.mean() / returns.std() * np.sqrt(288 * 365)

    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = abs(dd.min()) if len(dd) else 0.0

    wins = sum(1 for t in trades if t.pnl_net > 0)
    win_rate = wins / len(trades) if trades else 0.0

    total_fees = sum(t.fee_paid for t in trades)
    total_gross = sum(abs(t.pnl_gross) for t in trades)
    fee_ratio = total_fees / total_gross if total_gross > 0 else 0.0

    return BacktestResult(
        start=df["open_time"].iloc[0],
        end=df["open_time"].iloc[-1],
        num_trades=len(trades),
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown=max_dd,
        total_return_pct=(equity / initial_equity - 1) * 100,
        fee_ratio=fee_ratio,
        final_equity=equity,
        trades=trades,
    )


# ---------------------------------------------------------------------------
# Safety guards — reject suspicious or unusable results
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    passed: bool
    reasons: list[str]


def check_guards(result: BacktestResult) -> GuardResult:
    """Gates that a candidate strategy must pass before promotion.

    All thresholds are deliberately conservative. If a strategy looks
    too good to be true, it probably is (look-ahead bias or overfit).
    """
    reasons: list[str] = []

    if result.num_trades < MIN_TRADES_BACKTEST:
        reasons.append(f"too_few_trades ({result.num_trades} < {MIN_TRADES_BACKTEST})")

    if result.sharpe > 3.0:
        reasons.append(f"sharpe_suspicious ({result.sharpe:.2f} > 3.0 — likely look-ahead bias)")

    if result.sharpe < 0.5:
        reasons.append(f"sharpe_too_low ({result.sharpe:.2f} < 0.5)")

    if result.max_drawdown > 0.15:
        reasons.append(f"drawdown_excessive ({result.max_drawdown*100:.1f}% > 15%)")

    if result.win_rate > 0.80:
        reasons.append(f"win_rate_suspicious ({result.win_rate*100:.0f}% > 80%)")

    if result.win_rate < 0.30 and result.sharpe < 1.0:
        reasons.append(f"win_rate_too_low ({result.win_rate*100:.0f}% with low sharpe)")

    if result.fee_ratio > 0.30:
        reasons.append(f"fee_bleed ({result.fee_ratio*100:.0f}% fees > 30%)")

    if result.total_return_pct > 500:
        reasons.append(f"return_suspicious (+{result.total_return_pct:.0f}% — likely look-ahead)")

    return GuardResult(passed=len(reasons) == 0, reasons=reasons)


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _main():
        print(f"Loading {TRAIN_DAYS + VALIDATION_DAYS} days of {SYMBOL} {INTERVAL} data...")
        df = await load_historical(days=TRAIN_DAYS + VALIDATION_DAYS)
        print(f"  -> {len(df)} candles from {df['open_time'].min()} to {df['open_time'].max()}")
        train, val = walk_forward_split(df)
        print(f"  train: {len(train)} candles, val: {len(val)} candles")

        # Smoke test with baseline
        from strategy import Strategy
        strat = Strategy()
        print(f"\nRunning backtest with baseline strategy on validation data...")
        res = run_backtest(val, strat)
        print(json.dumps(res.summary(), indent=2, default=str))
        print("\nGuard check:")
        g = check_guards(res)
        print(f"  passed: {g.passed}")
        for r in g.reasons:
            print(f"  - {r}")

    asyncio.run(_main())

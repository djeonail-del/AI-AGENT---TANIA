"""
bot.py — Live trading bot (Champion).

Runs a strategy against Binance USDⓈ-M Futures testnet.
- Polls kline every poll_interval seconds
- Queries current position
- Places/exits orders with idempotent newClientOrderId
- Logs all trades to SQLite
- Respects kill switch (max drawdown, error rate)

Designed to run 24/7 under systemd or docker. Restart is safe — state is in SQLite.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import signal
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pandas as pd

from prepare import fetch_klines, SYMBOL, INTERVAL
from strategy import Strategy


# ---------------------------------------------------------------------------
# Config (via env)
# ---------------------------------------------------------------------------

REST_BASE = os.environ.get("BINANCE_TESTNET_REST_BASE", "https://testnet.binancefuture.com")
API_KEY = os.environ["BINANCE_TESTNET_API_KEY"]
API_SECRET = os.environ["BINANCE_TESTNET_API_SECRET"]

DB_PATH = Path(os.environ.get("BOT_DB_PATH", "/app/db/trades.db"))
LOG_PATH = Path(os.environ.get("BOT_LOG_PATH", "/app/db/bot.log"))

# Trading parameters (bot-level, not strategy-level)
LEVERAGE = int(os.environ.get("BOT_LEVERAGE", "2"))
POSITION_SIZE_PCT = float(os.environ.get("BOT_POSITION_SIZE_PCT", "0.10"))
STOP_LOSS_PCT = float(os.environ.get("BOT_STOP_LOSS_PCT", "0.01"))
TAKE_PROFIT_PCT = float(os.environ.get("BOT_TAKE_PROFIT_PCT", "0.02"))
MAX_DRAWDOWN_PCT = float(os.environ.get("BOT_MAX_DD_PCT", "0.05"))  # pause if -5% in 24h
POLL_INTERVAL = int(os.environ.get("BOT_POLL_INTERVAL", "30"))  # seconds

RECV_WINDOW = 5000


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bot")


# ---------------------------------------------------------------------------
# Binance client (signed REST)
# ---------------------------------------------------------------------------

def _sign(query: str) -> str:
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


async def signed_request(
    client: httpx.AsyncClient, method: str, path: str, params: dict | None = None
) -> dict:
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW
    qs = urlencode(params)
    sig = _sign(qs)
    url = f"{REST_BASE}{path}?{qs}&signature={sig}"
    headers = {"X-MBX-APIKEY": API_KEY}
    r = await client.request(method, url, headers=headers)
    if r.status_code >= 400:
        log.error(f"HTTP {r.status_code} on {method} {path}: {r.text[:500]}")
        r.raise_for_status()
    return r.json()


async def get_balance(client: httpx.AsyncClient) -> float:
    data = await signed_request(client, "GET", "/fapi/v3/account")
    return float(data["totalWalletBalance"])


async def get_position(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """Returns position dict or None if flat."""
    data = await signed_request(client, "GET", "/fapi/v3/positionRisk", {"symbol": symbol})
    for p in data:
        amt = float(p["positionAmt"])
        if abs(amt) > 1e-9:
            return p
    return None


async def set_leverage(client: httpx.AsyncClient, symbol: str, lev: int):
    try:
        await signed_request(client, "POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})
        log.info(f"Leverage set to {lev}x for {symbol}")
    except Exception as e:
        log.warning(f"Set leverage failed (may already be set): {e}")


async def place_market_order(
    client: httpx.AsyncClient,
    symbol: str,
    side: str,           # BUY or SELL
    qty: float,
    reduce_only: bool = False,
) -> dict:
    client_order_id = f"tania-{uuid.uuid4().hex[:16]}"
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": round(qty, 3),
        "newClientOrderId": client_order_id,
    }
    if reduce_only:
        params["reduceOnly"] = "true"
    return await signed_request(client, "POST", "/fapi/v1/order", params)


async def get_symbol_filters(client: httpx.AsyncClient, symbol: str) -> dict:
    r = await client.get(f"{REST_BASE}/fapi/v1/exchangeInfo")
    info = r.json()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            return {f["filterType"]: f for f in s["filters"]}
    raise ValueError(f"Symbol {symbol} not found")


# ---------------------------------------------------------------------------
# SQLite logging
# ---------------------------------------------------------------------------

def db_init(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).parent / "db" / "schema.sql").read_text()
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_event(level: str, message: str, context: str = ""):
    with db_conn() as c:
        c.execute(
            "INSERT INTO events (ts, level, message, context) VALUES (?, ?, ?, ?)",
            (int(time.time()), level, message, context),
        )


def log_order(side: str, qty: float, price: float, reason: str, order_resp: dict):
    with db_conn() as c:
        c.execute(
            "INSERT INTO orders (ts, symbol, side, qty, price, reason, order_id, client_order_id, raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(time.time()),
                SYMBOL,
                side,
                qty,
                price,
                reason,
                str(order_resp.get("orderId", "")),
                str(order_resp.get("clientOrderId", "")),
                str(order_resp),
            ),
        )


def log_equity(equity: float, unrealized_pnl: float = 0.0):
    with db_conn() as c:
        c.execute(
            "INSERT INTO equity_curve (ts, equity, unrealized_pnl) VALUES (?, ?, ?)",
            (int(time.time()), equity, unrealized_pnl),
        )


def get_equity_24h_ago() -> float | None:
    with db_conn() as c:
        cutoff = int(time.time()) - 86400
        row = c.execute(
            "SELECT equity FROM equity_curve WHERE ts <= ? ORDER BY ts DESC LIMIT 1", (cutoff,)
        ).fetchone()
        return row["equity"] if row else None


def is_paused() -> bool:
    with db_conn() as c:
        row = c.execute("SELECT value FROM state WHERE key = 'paused'").fetchone()
        return bool(int(row["value"])) if row else False


def set_pause(paused: bool, reason: str = ""):
    with db_conn() as c:
        c.execute(
            "INSERT INTO state (key, value, updated_ts) VALUES ('paused', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ("1" if paused else "0", int(time.time())),
        )
    log_event("WARN" if paused else "INFO", f"pause={paused}", reason)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def check_kill_switch(current_equity: float) -> tuple[bool, str]:
    """Return (should_pause, reason)."""
    eq_past = get_equity_24h_ago()
    if eq_past is None:
        return False, ""
    dd = (current_equity - eq_past) / eq_past
    if dd < -MAX_DRAWDOWN_PCT:
        return True, f"24h drawdown {dd*100:.2f}% < -{MAX_DRAWDOWN_PCT*100:.0f}%"
    return False, ""


# ---------------------------------------------------------------------------
# Order sizing
# ---------------------------------------------------------------------------

def calc_position_qty(equity: float, price: float, step_size: float, min_qty: float) -> float:
    notional = equity * POSITION_SIZE_PCT * LEVERAGE
    qty = notional / price
    # Round down to step_size
    qty = int(qty / step_size) * step_size
    return max(qty, min_qty)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run():
    db_init(DB_PATH)
    log_event("INFO", "bot_start", f"leverage={LEVERAGE} size={POSITION_SIZE_PCT} sl={STOP_LOSS_PCT} tp={TAKE_PROFIT_PCT}")

    strategy = Strategy()
    log.info(f"Strategy: {strategy.params()}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Setup
        filters = await get_symbol_filters(client, SYMBOL)
        step_size = float(filters["LOT_SIZE"]["stepSize"])
        min_qty = float(filters["LOT_SIZE"]["minQty"])
        log.info(f"{SYMBOL}: step={step_size} min_qty={min_qty}")

        await set_leverage(client, SYMBOL, LEVERAGE)

        error_count = 0
        last_signal = "NOOP"

        while True:
            try:
                # Poll market data
                df = await fetch_klines(SYMBOL, INTERVAL, limit=200)

                # Equity + kill switch
                equity = await get_balance(client)
                pos = await get_position(client, SYMBOL)
                upnl = float(pos["unRealizedProfit"]) if pos else 0.0
                log_equity(equity, upnl)

                if is_paused():
                    log.info(f"[PAUSED] equity=${equity:.2f} pos={'FLAT' if not pos else pos['positionAmt']}")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                should_pause, reason = check_kill_switch(equity)
                if should_pause:
                    log.error(f"[KILL SWITCH] {reason}")
                    set_pause(True, reason)
                    # Close any open position via reduce-only
                    if pos:
                        amt = float(pos["positionAmt"])
                        side = "SELL" if amt > 0 else "BUY"
                        resp = await place_market_order(client, SYMBOL, side, abs(amt), reduce_only=True)
                        log_order(side, abs(amt), 0, "kill_switch_close", resp)
                    continue

                # Strategy signal
                signal = strategy.on_candle(df)
                price = float(df["close"].iloc[-1])

                if signal != last_signal:
                    log.info(f"Signal: {signal} @ {price:.2f} | equity=${equity:.2f} | pos={'FLAT' if not pos else pos['positionAmt']}")
                    last_signal = signal

                # Decide action
                if pos is None:
                    if signal == "LONG":
                        qty = calc_position_qty(equity, price, step_size, min_qty)
                        resp = await place_market_order(client, SYMBOL, "BUY", qty)
                        log_order("BUY", qty, price, "signal_long", resp)
                        log.info(f"OPENED LONG {qty} @ ~{price:.2f}")
                    elif signal == "SHORT":
                        qty = calc_position_qty(equity, price, step_size, min_qty)
                        resp = await place_market_order(client, SYMBOL, "SELL", qty)
                        log_order("SELL", qty, price, "signal_short", resp)
                        log.info(f"OPENED SHORT {qty} @ ~{price:.2f}")
                else:
                    amt = float(pos["positionAmt"])
                    entry = float(pos["entryPrice"])
                    current_side = "LONG" if amt > 0 else "SHORT"

                    # Stop-loss / take-profit check
                    if current_side == "LONG":
                        pct = (price - entry) / entry
                    else:
                        pct = (entry - price) / entry

                    if pct <= -STOP_LOSS_PCT:
                        close_side = "SELL" if amt > 0 else "BUY"
                        resp = await place_market_order(client, SYMBOL, close_side, abs(amt), reduce_only=True)
                        log_order(close_side, abs(amt), price, "stop_loss", resp)
                        log.info(f"STOPPED OUT {current_side} @ {price:.2f} ({pct*100:.2f}%)")
                    elif pct >= TAKE_PROFIT_PCT:
                        close_side = "SELL" if amt > 0 else "BUY"
                        resp = await place_market_order(client, SYMBOL, close_side, abs(amt), reduce_only=True)
                        log_order(close_side, abs(amt), price, "take_profit", resp)
                        log.info(f"TOOK PROFIT {current_side} @ {price:.2f} (+{pct*100:.2f}%)")
                    elif signal in ("LONG", "SHORT") and signal != current_side:
                        # Signal flip → close, then open opposite
                        close_side = "SELL" if amt > 0 else "BUY"
                        resp = await place_market_order(client, SYMBOL, close_side, abs(amt), reduce_only=True)
                        log_order(close_side, abs(amt), price, "signal_flip_close", resp)
                        log.info(f"FLIPPED — closed {current_side} @ {price:.2f}")

                error_count = 0  # reset on successful loop

            except KeyboardInterrupt:
                log.info("Interrupted — stopping.")
                break
            except Exception as e:
                error_count += 1
                log.exception(f"Loop error ({error_count}): {e}")
                log_event("ERROR", str(e), "main_loop")
                if error_count >= 10:
                    log.error("10 consecutive errors — pausing bot.")
                    set_pause(True, "error_cascade")

            await asyncio.sleep(POLL_INTERVAL)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _graceful(_sig, _frame):
        log.info("Received stop signal, exiting.")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)
    loop.run_until_complete(run())

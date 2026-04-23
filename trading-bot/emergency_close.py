"""
emergency_close.py — Panic button.

Usage:
    python emergency_close.py

What it does:
1. Sets bot to paused (so main loop won't reopen).
2. Queries all open positions.
3. Closes each via reduce-only market order.
4. Cancels all open orders.
5. Logs the event.

Run manually, or wire to Telegram /panic command, or systemctl stop trading-bot followed by this.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

from bot import (
    db_conn,
    get_position,
    place_market_order,
    set_pause,
    signed_request,
    log_order,
    log_event,
    REST_BASE,
    API_KEY,
)
from prepare import SYMBOL


async def run():
    print("=== EMERGENCY CLOSE ALL ===")
    set_pause(True, "emergency_close_manual")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Cancel all open orders for symbol
        try:
            await signed_request(client, "DELETE", "/fapi/v1/allOpenOrders", {"symbol": SYMBOL})
            print(f"✓ Cancelled all open orders for {SYMBOL}")
        except Exception as e:
            print(f"✗ Cancel open orders failed: {e}")

        # Close position if any
        pos = await get_position(client, SYMBOL)
        if pos is None:
            print(f"✓ No open position for {SYMBOL}")
        else:
            amt = float(pos["positionAmt"])
            side = "SELL" if amt > 0 else "BUY"
            print(f"  Closing {amt} {SYMBOL} via {side} reduce-only...")
            resp = await place_market_order(client, SYMBOL, side, abs(amt), reduce_only=True)
            log_order(side, abs(amt), 0, "emergency_close", resp)
            print(f"✓ Close order sent: {resp.get('orderId')}")

    log_event("WARN", "emergency_close_executed", "panic_button")
    print("=== DONE. Bot is PAUSED. Restart manually via: python -c 'from bot import set_pause; set_pause(False)' ===")


if __name__ == "__main__":
    asyncio.run(run())

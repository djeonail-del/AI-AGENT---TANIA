"""
research.py — AutoResearch loop (Fase 1 MVP: random search over strategy params).

Forever loop:
  1. Mutate current champion params (or start from baseline).
  2. Run backtest on training data.
  3. If guards pass, re-run on validation data.
  4. If still passes + better than champion → save candidate.
  5. Log to candidates table.

No LLM required for MVP — simple random search. Later we can swap in
Anthropic/OpenAI calls to generate smarter mutations.

Respects the same "separation of concerns" as Karpathy's autoresearch:
- prepare.py is untouched (ground-truth metric)
- strategy.py is the knob-space
- This file is the search engine
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path

from prepare import (
    load_historical,
    walk_forward_split,
    run_backtest,
    check_guards,
    TRAIN_DAYS,
    VALIDATION_DAYS,
)
from strategy import Strategy

DB_PATH = Path(os.environ.get("BOT_DB_PATH", "/app/db/trades.db"))
LOG_PATH = Path(os.environ.get("RESEARCH_LOG_PATH", "/app/db/research.log"))

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("research")


# ---------------------------------------------------------------------------
# Parameter space (mutation bounds)
# ---------------------------------------------------------------------------

PARAM_SPACE = {
    "rsi_period":     {"type": "int",   "min": 5,   "max": 30},
    "rsi_oversold":   {"type": "float", "min": 15,  "max": 40},
    "rsi_overbought": {"type": "float", "min": 60,  "max": 85},
    "ema_period":     {"type": "int",   "min": 20,  "max": 200},
}


def random_params() -> dict:
    p = {}
    for k, spec in PARAM_SPACE.items():
        if spec["type"] == "int":
            p[k] = random.randint(spec["min"], spec["max"])
        else:
            p[k] = round(random.uniform(spec["min"], spec["max"]), 2)
    return p


def mutate(params: dict, mutation_rate: float = 0.3) -> dict:
    """Perturb current params slightly. Each param has `mutation_rate` chance to change."""
    new = dict(params)
    for k, spec in PARAM_SPACE.items():
        if random.random() < mutation_rate:
            if spec["type"] == "int":
                delta = random.randint(-5, 5)
                new[k] = max(spec["min"], min(spec["max"], new[k] + delta))
            else:
                delta = random.uniform(-5, 5)
                new[k] = round(max(spec["min"], min(spec["max"], new[k] + delta)), 2)
    return new


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def db_conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def load_champion() -> dict | None:
    with db_conn() as c:
        row = c.execute(
            "SELECT params_json FROM candidates WHERE is_champion = 1 ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["params_json"]) if row else None


def save_candidate(
    generation: int,
    params: dict,
    train_res,
    val_res,
    guard,
) -> int:
    with db_conn() as c:
        cur = c.execute(
            """INSERT INTO candidates
               (ts, generation, params_json, train_sharpe, val_sharpe, max_dd, win_rate, fee_ratio, num_trades, passed_guards, reasons, is_champion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                int(time.time()),
                generation,
                json.dumps(params),
                train_res.sharpe if train_res else None,
                val_res.sharpe if val_res else None,
                val_res.max_drawdown if val_res else None,
                val_res.win_rate if val_res else None,
                val_res.fee_ratio if val_res else None,
                val_res.num_trades if val_res else None,
                1 if guard.passed else 0,
                json.dumps(guard.reasons),
            ),
        )
        return cur.lastrowid


def init_baseline_as_champion(params: dict):
    """Insert baseline as initial champion if no champion exists yet."""
    with db_conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM candidates WHERE is_champion = 1").fetchone()
        if row["n"] == 0:
            c.execute(
                """INSERT INTO candidates
                   (ts, generation, params_json, passed_guards, reasons, is_champion)
                   VALUES (?, 0, ?, 1, '[]', 1)""",
                (int(time.time()), json.dumps(params)),
            )
            log.info(f"Seeded baseline champion: {params}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run():
    log.info("Loading historical data...")
    df = await load_historical(days=TRAIN_DAYS + VALIDATION_DAYS)
    log.info(f"Loaded {len(df)} candles from {df['open_time'].min()} to {df['open_time'].max()}")
    train, val = walk_forward_split(df)
    log.info(f"train={len(train)} candles, val={len(val)} candles")

    baseline = Strategy().params()
    # Strip the name field — not a tunable param
    baseline = {k: v for k, v in baseline.items() if k != "name"}
    init_baseline_as_champion(baseline)

    generation = 0
    best_val_sharpe = -float("inf")

    while True:
        generation += 1
        try:
            champion_params = load_champion() or baseline

            # Mix of pure random (explore) vs mutate (exploit)
            if random.random() < 0.3:
                params = random_params()
                strategy_type = "random"
            else:
                params = mutate(champion_params)
                strategy_type = "mutated"

            strat = Strategy(**params)

            # Quick train backtest
            train_res = run_backtest(train, strat)
            train_guard = check_guards(train_res)

            if not train_guard.passed:
                log.info(f"gen {generation} [{strategy_type}] train FAIL: {train_guard.reasons}")
                save_candidate(generation, params, train_res, None, train_guard)
                continue

            # Validate on held-out data
            val_res = run_backtest(val, strat)
            val_guard = check_guards(val_res)

            status = "PASS" if val_guard.passed else "FAIL"
            log.info(
                f"gen {generation} [{strategy_type}] train_sharpe={train_res.sharpe:.2f} "
                f"val_sharpe={val_res.sharpe:.2f} dd={val_res.max_drawdown*100:.1f}% "
                f"trades={val_res.num_trades} → {status}"
            )
            cand_id = save_candidate(generation, params, train_res, val_res, val_guard)

            if val_guard.passed and val_res.sharpe > best_val_sharpe:
                log.info(f"  ⭐ new best: val_sharpe={val_res.sharpe:.2f} (prev={best_val_sharpe:.2f})")
                best_val_sharpe = val_res.sharpe

        except KeyboardInterrupt:
            log.info("Interrupted — stopping.")
            break
        except Exception as e:
            log.exception(f"gen {generation} error: {e}")

        # Gentle pacing — don't hammer CPU
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())

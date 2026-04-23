-- SQLite schema for tania-trading bot
-- Idempotent: CREATE IF NOT EXISTS everywhere

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,           -- BUY / SELL
    qty             REAL NOT NULL,
    price           REAL NOT NULL,
    reason          TEXT NOT NULL,           -- signal_long / signal_short / stop_loss / take_profit / signal_flip_close / kill_switch_close
    order_id        TEXT,
    client_order_id TEXT,
    raw             TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);

CREATE TABLE IF NOT EXISTS equity_curve (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    equity          REAL NOT NULL,
    unrealized_pnl  REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_curve(ts);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    level           TEXT NOT NULL,           -- INFO / WARN / ERROR
    message         TEXT NOT NULL,
    context         TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS state (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_ts      INTEGER NOT NULL
);

-- Research candidates (written by research.py, read by check_and_promote cron)
CREATE TABLE IF NOT EXISTS candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    generation      INTEGER NOT NULL,
    params_json     TEXT NOT NULL,
    train_sharpe    REAL,
    val_sharpe      REAL,
    max_dd          REAL,
    win_rate        REAL,
    fee_ratio       REAL,
    num_trades      INTEGER,
    passed_guards   INTEGER NOT NULL,        -- 0 / 1
    reasons         TEXT,
    is_champion     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_candidates_ts ON candidates(ts);

-- Strategy promotion history
CREATE TABLE IF NOT EXISTS promotions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              INTEGER NOT NULL,
    from_candidate  INTEGER,
    to_candidate    INTEGER NOT NULL,
    reason          TEXT,
    FOREIGN KEY (from_candidate) REFERENCES candidates(id),
    FOREIGN KEY (to_candidate)   REFERENCES candidates(id)
);

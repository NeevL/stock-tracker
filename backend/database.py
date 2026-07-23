"""
database.py
Handles SQLite schema creation and gives every other module a single
place to grab a connection from.

Tables:
  companies        -- static reference data (one row per company)
  price_snapshots   -- one row per company, overwritten on every refresh
                       (this is what powers "live" price / P/E / EPS / mcap)
  price_history     -- append-only daily OHLC candles used for charts
                       and for computing 52-week highs/lows
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "stocks.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    ticker      TEXT PRIMARY KEY,      -- NSE symbol, e.g. RELIANCE
    yf_symbol   TEXT NOT NULL,         -- yfinance symbol, e.g. RELIANCE.NS
    name        TEXT NOT NULL,
    sector      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    ticker          TEXT PRIMARY KEY REFERENCES companies(ticker),
    price           REAL,
    prev_close      REAL,
    day_change      REAL,
    day_change_pct  REAL,
    market_cap      REAL,             -- in INR crore
    pe_ratio        REAL,
    eps             REAL,
    pb_ratio        REAL,
    dividend_yield  REAL,
    week52_high     REAL,
    week52_low      REAL,
    volume          INTEGER,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT REFERENCES companies(ticker),
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    UNIQUE(ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_history_ticker_date
    ON price_history(ticker, date);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")

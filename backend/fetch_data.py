"""
fetch_data.py
Populates / refreshes the database.

Two modes:
  - live mode  (default when yfinance can reach the internet):
        pulls real quotes + fundamentals + 6 months of daily candles
        for every ticker via the `yfinance` library.
  - mock mode  (automatic fallback, or force with --mock):
        generates realistic-looking synthetic data so the app is fully
        demoable in sandboxed / offline environments (e.g. this build
        environment has no route to Yahoo Finance's servers).

Run directly to seed/refresh the DB:
    python fetch_data.py            # tries live, falls back to mock
    python fetch_data.py --mock     # force synthetic data
    python fetch_data.py --live     # force live, error if unreachable
"""

import argparse
import datetime as dt
import math
import random
import sys

from database import get_conn, init_db

# 20 well-known NSE-listed companies across sectors.
# ticker    = clean symbol used throughout our API / DB
# yf_symbol = symbol yfinance expects (NSE tickers need the ".NS" suffix)
COMPANIES = [
    ("RELIANCE",   "RELIANCE.NS",   "Reliance Industries",        "Energy/Conglomerate"),
    ("TCS",        "TCS.NS",        "Tata Consultancy Services",  "IT Services"),
    ("HDFCBANK",   "HDFCBANK.NS",   "HDFC Bank",                  "Banking"),
    ("INFY",       "INFY.NS",       "Infosys",                    "IT Services"),
    ("ICICIBANK",  "ICICIBANK.NS",  "ICICI Bank",                 "Banking"),
    ("HINDUNILVR", "HINDUNILVR.NS", "Hindustan Unilever",         "FMCG"),
    ("ITC",        "ITC.NS",        "ITC Limited",                "FMCG"),
    ("SBIN",       "SBIN.NS",       "State Bank of India",        "Banking"),
    ("BHARTIARTL", "BHARTIARTL.NS", "Bharti Airtel",              "Telecom"),
    ("LT",         "LT.NS",         "Larsen & Toubro",            "Infrastructure"),
    ("KOTAKBANK",  "KOTAKBANK.NS",  "Kotak Mahindra Bank",        "Banking"),
    ("BAJFINANCE", "BAJFINANCE.NS", "Bajaj Finance",              "NBFC"),
    ("ASIANPAINT", "ASIANPAINT.NS", "Asian Paints",               "Consumer Durables"),
    ("MARUTI",     "MARUTI.NS",     "Maruti Suzuki India",        "Automobile"),
    ("TITAN",      "TITAN.NS",      "Titan Company",              "Consumer Durables"),
    ("SUNPHARMA",  "SUNPHARMA.NS",  "Sun Pharmaceutical",         "Pharma"),
    ("WIPRO",      "WIPRO.NS",      "Wipro",                      "IT Services"),
    ("ULTRACEMCO", "ULTRACEMCO.NS", "UltraTech Cement",           "Cement"),
    ("NESTLEIND",  "NESTLEIND.NS",  "Nestle India",               "FMCG"),
    ("TATAMOTORS", "TATAMOTORS.NS", "Tata Motors",                "Automobile"),
]


def seed_companies():
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO companies (ticker, yf_symbol, name, sector) "
            "VALUES (?, ?, ?, ?)",
            COMPANIES,
        )


# ----------------------------------------------------------------------
# LIVE MODE
# ----------------------------------------------------------------------
def fetch_live():
    import yfinance as yf

    with get_conn() as conn:
        for ticker, yf_symbol, name, sector in COMPANIES:
            t = yf.Ticker(yf_symbol)
            info = t.info  # fundamentals + latest quote fields
            hist = t.history(period="6mo", interval="1d")

            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose")
            day_change = (price - prev_close) if (price and prev_close) else None
            day_change_pct = (day_change / prev_close * 100) if day_change and prev_close else None

            conn.execute(
                """INSERT INTO price_snapshots
                   (ticker, price, prev_close, day_change, day_change_pct, market_cap,
                    pe_ratio, eps, pb_ratio, dividend_yield, week52_high, week52_low,
                    volume, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET
                    price=excluded.price, prev_close=excluded.prev_close,
                    day_change=excluded.day_change, day_change_pct=excluded.day_change_pct,
                    market_cap=excluded.market_cap, pe_ratio=excluded.pe_ratio,
                    eps=excluded.eps, pb_ratio=excluded.pb_ratio,
                    dividend_yield=excluded.dividend_yield, week52_high=excluded.week52_high,
                    week52_low=excluded.week52_low, volume=excluded.volume,
                    updated_at=excluded.updated_at""",
                (
                    ticker, price, prev_close, day_change, day_change_pct,
                    (info.get("marketCap") or 0) / 1e7,  # paise->rupees already; convert to INR crore
                    info.get("trailingPE"), info.get("trailingEps"), info.get("priceToBook"),
                    (info.get("dividendYield") or 0) * 100,
                    info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow"),
                    info.get("volume"), dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )

            for date_idx, row in hist.iterrows():
                conn.execute(
                    """INSERT OR IGNORE INTO price_history
                       (ticker, date, open, high, low, close, volume)
                       VALUES (?,?,?,?,?,?,?)""",
                    (ticker, date_idx.strftime("%Y-%m-%d"),
                     row["Open"], row["High"], row["Low"], row["Close"], int(row["Volume"])),
                )
            print(f"[live] {ticker} updated")


# ----------------------------------------------------------------------
# MOCK MODE (deterministic-ish synthetic data, used when there's no
# network route to Yahoo Finance -- e.g. in this sandboxed build env)
# ----------------------------------------------------------------------
# Rough anchor prices / fundamentals so the demo data looks plausible.
MOCK_ANCHORS = {
    "RELIANCE":   dict(price=2950, pe=24.5, eps=120.4, mcap=1998000),
    "TCS":        dict(price=3850, pe=28.1, eps=137.0, mcap=1394000),
    "HDFCBANK":   dict(price=1720, pe=19.8, eps=86.9,  mcap=1317000),
    "INFY":       dict(price=1850, pe=26.4, eps=70.1,  mcap=767000),
    "ICICIBANK":  dict(price=1290, pe=18.9, eps=68.3,  mcap=907000),
    "HINDUNILVR": dict(price=2450, pe=54.2, eps=45.2,  mcap=576000),
    "ITC":        dict(price=465,  pe=27.6, eps=16.8,  mcap=581000),
    "SBIN":       dict(price=845,  pe=10.2, eps=82.8,  mcap=754000),
    "BHARTIARTL": dict(price=1580, pe=68.4, eps=23.1,  mcap=948000),
    "LT":         dict(price=3620, pe=32.5, eps=111.4, mcap=498000),
    "KOTAKBANK":  dict(price=1780, pe=17.6, eps=101.1, mcap=354000),
    "BAJFINANCE": dict(price=7150, pe=31.2, eps=229.2, mcap=442000),
    "ASIANPAINT": dict(price=2380, pe=44.8, eps=53.1,  mcap=228000),
    "MARUTI":     dict(price=12450,pe=27.9, eps=446.1, mcap=396000),
    "TITAN":      dict(price=3320, pe=68.7, eps=48.3,  mcap=294000),
    "SUNPHARMA":  dict(price=1780, pe=34.6, eps=51.4,  mcap=427000),
    "WIPRO":      dict(price=545,  pe=22.4, eps=24.3,  mcap=285000),
    "ULTRACEMCO": dict(price=11250,pe=38.9, eps=289.2, mcap=324000),
    "NESTLEIND":  dict(price=2280, pe=61.3, eps=37.2,  mcap=219000),
    "TATAMOTORS": dict(price=985,  pe=12.1, eps=81.4,  mcap=362000),
}


def _seeded_random(ticker):
    return random.Random(sum(ord(c) for c in ticker))


def fetch_mock():
    today = dt.date.today()
    with get_conn() as conn:
        for ticker, yf_symbol, name, sector in COMPANIES:
            rnd = _seeded_random(ticker)
            anchor = MOCK_ANCHORS[ticker]

            # --- build 180 days of synthetic OHLC via a random walk ---
            price = anchor["price"] * 0.85  # start ~15% below current anchor
            candles = []
            for i in range(180, 0, -1):
                date = today - dt.timedelta(days=i)
                if date.weekday() >= 5:  # skip weekends
                    continue
                drift = (anchor["price"] - price) * 0.01  # gentle pull toward anchor
                shock = price * rnd.uniform(-0.018, 0.018)
                price = max(1, price + drift + shock)
                open_p = price * rnd.uniform(0.995, 1.005)
                high_p = max(open_p, price) * rnd.uniform(1.0, 1.012)
                low_p = min(open_p, price) * rnd.uniform(0.988, 1.0)
                volume = int(rnd.uniform(5e5, 8e6))
                candles.append((ticker, date.isoformat(), round(open_p, 2), round(high_p, 2),
                                 round(low_p, 2), round(price, 2), volume))

            conn.executemany(
                """INSERT OR IGNORE INTO price_history
                   (ticker, date, open, high, low, close, volume)
                   VALUES (?,?,?,?,?,?,?)""",
                candles,
            )

            last_close = candles[-1][5]
            prev_close = candles[-2][5] if len(candles) > 1 else last_close
            day_change = last_close - prev_close
            day_change_pct = (day_change / prev_close * 100) if prev_close else 0
            closes = [c[5] for c in candles]

            conn.execute(
                """INSERT INTO price_snapshots
                   (ticker, price, prev_close, day_change, day_change_pct, market_cap,
                    pe_ratio, eps, pb_ratio, dividend_yield, week52_high, week52_low,
                    volume, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET
                    price=excluded.price, prev_close=excluded.prev_close,
                    day_change=excluded.day_change, day_change_pct=excluded.day_change_pct,
                    market_cap=excluded.market_cap, pe_ratio=excluded.pe_ratio,
                    eps=excluded.eps, pb_ratio=excluded.pb_ratio,
                    dividend_yield=excluded.dividend_yield, week52_high=excluded.week52_high,
                    week52_low=excluded.week52_low, volume=excluded.volume,
                    updated_at=excluded.updated_at""",
                (
                    ticker, round(last_close, 2), round(prev_close, 2),
                    round(day_change, 2), round(day_change_pct, 2),
                    round(anchor["mcap"] * rnd.uniform(0.98, 1.02), 1),
                    round(anchor["pe"] * rnd.uniform(0.97, 1.03), 2),
                    round(anchor["eps"] * rnd.uniform(0.98, 1.02), 2),
                    round(rnd.uniform(2.5, 14), 2),
                    round(rnd.uniform(0.3, 2.8), 2),
                    round(max(closes) * 1.03, 2),
                    round(min(closes) * 0.97, 2),
                    candles[-1][6],
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )
            print(f"[mock] {ticker} seeded")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="force synthetic data")
    parser.add_argument("--live", action="store_true", help="force live yfinance fetch")
    args = parser.parse_args()

    init_db()
    seed_companies()

    if args.mock:
        fetch_mock()
        return
    if args.live:
        fetch_live()
        return

    # default: try live, fall back to mock
    try:
        fetch_live()
    except Exception as e:
        print(f"Live fetch unavailable ({e.__class__.__name__}: {e}); using mock data instead.",
              file=sys.stderr)
        fetch_mock()


if __name__ == "__main__":
    main()

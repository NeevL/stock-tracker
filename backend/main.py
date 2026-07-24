"""
main.py -- REST API for the Indian Equities Tracker.

Endpoints:
  GET  /api/stocks                     list every tracked company + latest snapshot
  GET  /api/stocks/{ticker}            full detail for one company
  GET  /api/stocks/{ticker}/history    daily OHLC candles (for charting)
  GET  /api/market-summary             aggregate market-wide stats
  POST /api/refresh                    re-fetch data (live if possible, else mock)

Also serves the static frontend dashboard at /.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    from .database import get_conn, init_db
    from . import fetch_data
except ImportError:  # allow running main.py directly from the backend folder
    from database import get_conn, init_db
    import fetch_data

app = FastAPI(title="Indian Equities Tracker API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    # Seed the DB automatically on first run so the app is usable immediately.
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM companies").fetchone()["c"]
    if count == 0:
        fetch_data.seed_companies()
        with get_conn() as conn:
            snap_count = conn.execute("SELECT COUNT(*) AS c FROM price_snapshots").fetchone()["c"]
        if snap_count == 0:
            try:
                fetch_data.fetch_live()
            except Exception:
                fetch_data.fetch_mock()


def _row_to_stock(row) -> dict:
    return {
        "ticker": row["ticker"],
        "name": row["name"],
        "sector": row["sector"],
        "price": row["price"],
        "prev_close": row["prev_close"],
        "day_change": row["day_change"],
        "day_change_pct": row["day_change_pct"],
        "market_cap_cr": row["market_cap"],
        "pe_ratio": row["pe_ratio"],
        "eps": row["eps"],
        "pb_ratio": row["pb_ratio"],
        "dividend_yield_pct": row["dividend_yield"],
        "week52_high": row["week52_high"],
        "week52_low": row["week52_low"],
        "volume": row["volume"],
        "updated_at": row["updated_at"],
    }


@app.get("/api/stocks")
def list_stocks(sector: str | None = None, sort_by: str = "market_cap_cr", order: str = "desc"):
    """
    Returns every tracked company merged with its latest snapshot.
    Optional query params:
      sector   -- filter by sector, e.g. ?sector=Banking
      sort_by  -- one of price, market_cap_cr, pe_ratio, eps, day_change_pct (default market_cap_cr)
      order    -- asc | desc (default desc)
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.ticker, c.name, c.sector, s.*
               FROM companies c LEFT JOIN price_snapshots s ON c.ticker = s.ticker"""
        ).fetchall()

    stocks = [_row_to_stock(r) for r in rows]

    if sector:
        stocks = [s for s in stocks if s["sector"].lower() == sector.lower()]

    valid_sort_keys = {"price", "market_cap_cr", "pe_ratio", "eps", "day_change_pct"}
    if sort_by not in valid_sort_keys:
        sort_by = "market_cap_cr"
    stocks.sort(key=lambda s: (s[sort_by] is None, s[sort_by]), reverse=(order != "asc"))

    return {"count": len(stocks), "stocks": stocks}


@app.get("/api/stocks/{ticker}")
def get_stock(ticker: str):
    """Full detail for a single company, including basic recent-history stats."""
    ticker = ticker.upper()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT c.ticker, c.name, c.sector, s.*
               FROM companies c LEFT JOIN price_snapshots s ON c.ticker = s.ticker
               WHERE c.ticker = ?""",
            (ticker,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")

        history_count = conn.execute(
            "SELECT COUNT(*) AS c FROM price_history WHERE ticker = ?", (ticker,)
        ).fetchone()["c"]

    stock = _row_to_stock(row)
    stock["history_points_available"] = history_count
    return stock


@app.get("/api/stocks/{ticker}/history")
def get_stock_history(ticker: str, days: int = 180):
    """Daily OHLC candles for charting. ?days= controls how far back to go (default 180)."""
    ticker = ticker.upper()
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")
        rows = conn.execute(
            """SELECT date, open, high, low, close, volume FROM price_history
               WHERE ticker = ? ORDER BY date DESC LIMIT ?""",
            (ticker, days),
        ).fetchall()

    candles = [dict(r) for r in rows][::-1]  # chronological order
    return {"ticker": ticker, "count": len(candles), "candles": candles}


@app.get("/api/market-summary")
def market_summary():
    """Aggregate, market-wide statistics across every tracked company."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.ticker, c.name, c.sector, s.*
               FROM companies c LEFT JOIN price_snapshots s ON c.ticker = s.ticker"""
        ).fetchall()

    stocks = [_row_to_stock(r) for r in rows if r["price"] is not None]
    if not stocks:
        return {"message": "No data yet -- POST /api/refresh first."}

    gainers = sorted([s for s in stocks if (s["day_change_pct"] or 0) > 0],
                      key=lambda s: s["day_change_pct"], reverse=True)
    losers = sorted([s for s in stocks if (s["day_change_pct"] or 0) < 0],
                     key=lambda s: s["day_change_pct"])

    total_mcap = sum(s["market_cap_cr"] or 0 for s in stocks)
    avg_pe = sum(s["pe_ratio"] or 0 for s in stocks if s["pe_ratio"]) / max(
        1, len([s for s in stocks if s["pe_ratio"]])
    )

    by_sector: dict[str, dict] = {}
    for s in stocks:
        b = by_sector.setdefault(s["sector"], {"count": 0, "market_cap_cr": 0.0})
        b["count"] += 1
        b["market_cap_cr"] += s["market_cap_cr"] or 0

    return {
        "companies_tracked": len(stocks),
        "total_market_cap_cr": round(total_mcap, 1),
        "average_pe_ratio": round(avg_pe, 2),
        "advancing": len(gainers),
        "declining": len(losers),
        "unchanged": len(stocks) - len(gainers) - len(losers),
        "top_gainer": gainers[0] if gainers else None,
        "top_loser": losers[0] if losers else None,
        "sector_breakdown": by_sector,
        "last_updated": max((s["updated_at"] for s in stocks if s["updated_at"]), default=None),
    }


@app.post("/api/refresh")
def refresh_data():
    """
    Re-fetches market data for all tracked companies: tries a live
    yfinance pull first, and transparently falls back to the synthetic
    data generator if there's no network route to Yahoo Finance.
    """
    try:
        fetch_data.fetch_live()
        return {"status": "ok", "mode": "live"}
    except Exception as e:
        fetch_data.fetch_mock()
        return {"status": "ok", "mode": "mock", "reason": f"{e.__class__.__name__}: {e}"}


# --- serve the frontend dashboard ---
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

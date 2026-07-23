# NSE Watch — Indian Equities Tracker

A full-stack web app that tracks 20 major NSE-listed Indian companies: fetches
market data, stores it in SQLite, and serves it through a REST API to a
terminal-style dashboard.

## Stack
- **Backend:** FastAPI + SQLite (`backend/`)
- **Data source:** [`yfinance`](https://pypi.org/project/yfinance/) (live Yahoo Finance data for NSE tickers), with an automatic synthetic-data fallback so the app is always demoable even without a route to Yahoo's servers
- **Frontend:** a single static HTML/CSS/JS dashboard (`frontend/`), no build step, served directly by FastAPI

## Companies tracked (20)
RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, HINDUNILVR, ITC, SBIN, BHARTIARTL, LT,
KOTAKBANK, BAJFINANCE, ASIANPAINT, MARUTI, TITAN, SUNPHARMA, WIPRO, ULTRACEMCO,
NESTLEIND, TATAMOTORS — spanning banking, IT, FMCG, energy, auto, pharma, cement,
and more. Edit `COMPANIES` in `backend/fetch_data.py` to track a different set.

## Database design
`backend/database.py` defines three tables:
- `companies` — static reference data (ticker, name, sector)
- `price_snapshots` — **one row per company**, upserted on every refresh; this
  is the "live" data (price, market cap, P/E, EPS, P/B, dividend yield, 52w
  high/low, volume). Efficient to update because it's a single `INSERT ... ON
  CONFLICT DO UPDATE` per company rather than an ever-growing table.
- `price_history` — append-only daily OHLC candles (indexed on
  `ticker, date`), used for the chart in the dashboard and for computing
  52-week ranges.

## REST API
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/stocks` | All 20 companies + latest snapshot. Supports `?sector=`, `?sort_by=`, `?order=` |
| GET | `/api/stocks/{ticker}` | Full detail for one company |
| GET | `/api/stocks/{ticker}/history?days=180` | Daily OHLC candles for charting |
| GET | `/api/market-summary` | Aggregate stats: total market cap, average P/E, advancers/decliners, top gainer/loser, sector breakdown |
| POST | `/api/refresh` | Re-fetches data (live if reachable, else synthetic) |

## Running it

```bash
cd backend
pip install -r requirements.txt

# seed the database (tries live Yahoo Finance data, falls back to
# realistic synthetic data automatically if there's no internet route)
python fetch_data.py

# start the API + dashboard
python -m uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** in a browser.

To force one mode explicitly: `python fetch_data.py --live` or `python fetch_data.py --mock`.

> **Note on this build environment:** the sandbox used to build and test this
> project has no outbound network route to Yahoo Finance's servers, so it was
> validated end-to-end using the synthetic data generator. The `fetch_live()`
> code path in `fetch_data.py` is real, standard `yfinance` usage — when run
> on a machine with normal internet access it will pull genuine live NSE
> quotes and fundamentals instead.

## Dashboard features
- Scrolling ticker tape of all 20 stocks with live price & day change
- Summary cards: total market cap, average P/E, advancing/declining count, top gainer/loser
- Sortable, searchable, sector-filterable table with Price, % Change, Market Cap, P/E, EPS, P/B, Dividend Yield
- Click any row for a detail panel with a 6-month price chart and full metrics
- "Refresh Data" button triggers `POST /api/refresh` live from the UI

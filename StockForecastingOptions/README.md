# Options Lookup

Stock options dashboard: contract history, 5-day forecasts, what-if Greeks,
watchlist scanners, SMA tools, put/call dominance, and cached contracts.

Data source: **Yahoo Finance** via [`yfinance`](https://github.com/ranaroussi/yfinance).

---

## How to run

### Easiest — one startup script (recommended)

Starts the virtualenv, backend, and frontend in one terminal. **Ctrl+C** stops both.

```bash
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions
./start.sh              # start backend + frontend
./start.sh --install    # pip + npm install first, then start
```

When ready, the script prints:

```
  UI (open in browser):  http://localhost:5173
  API:                   http://127.0.0.1:8000
  API docs:              http://127.0.0.1:8000/docs
```

### Manual — two terminals

Use **two terminals** if you prefer to run services separately. The virtual environment lives in the parent `WORK4` folder; app code is in `StockForecastingOptions/`.

### Project layout

```
/Users/sriramsreedhar/WORK4/
├── .venv/                          ← virtual environment
└── StockForecastingOptions/        ← app code (this folder)
    ├── backend/
    ├── frontend/
    ├── services/
    ├── cache.py
    ├── forecasting.py
    ├── start.sh                    ← one-command startup (backend + frontend)
    └── app.py                      ← legacy Streamlit (optional)
```

### One-time setup (first run only)

```bash
cd /Users/sriramsreedhar/WORK4
python3 -m venv .venv
source /Users/sriramsreedhar/WORK4/.venv/bin/activate
pip install -r StockForecastingOptions/requirements.txt

cd /Users/sriramsreedhar/WORK4/StockForecastingOptions/frontend
npm install
```

### Every time — Terminal 1 (API)

```bash
source /Users/sriramsreedhar/WORK4/.venv/bin/activate
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### Every time — Terminal 2 (React UI)

```bash
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions/frontend
npm install
npm run dev
```

Open **http://localhost:5173**

- Vite proxies `/api` → `http://127.0.0.1:8000`
- API docs: **http://127.0.0.1:8000/docs**

Press `Ctrl+C` in each terminal to stop.

> **Paths to remember**
>
> - Activate: `/Users/sriramsreedhar/WORK4/.venv/bin/activate`
> - App folder: `/Users/sriramsreedhar/WORK4/StockForecastingOptions`
> - Do **not** `cd` into `.venv` before activating — run the `source` command from anywhere

### Optional: one-line alias

Add to `~/.zshrc`:

```bash
alias runoptions-api='source /Users/sriramsreedhar/WORK4/.venv/bin/activate && cd /Users/sriramsreedhar/WORK4/StockForecastingOptions && uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000'
alias runoptions-ui='cd /Users/sriramsreedhar/WORK4/StockForecastingOptions/frontend && npm run dev'
```

### Production build (optional)

```bash
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions/frontend
npm run build
```

---

## Features mapped

Each dashboard tab in the React UI calls the FastAPI backend:

| Tab | React UI | API |
|-----|----------|-----|
| Recent Activity | ✓ | `POST /api/contract/lookup` |
| 5-Day Forecasts | ✓ (4 sub-models) | `POST /api/contract/forecasts` |
| What-If Scenario | ✓ | `POST /api/contract/what-if` |
| Track the Best | ✓ | `GET /api/watchlist/movers` |
| Quick Summary | ✓ | `GET /api/watchlist/summary` |
| Check SMA | ✓ | `POST /api/sma/check` |
| Calls vs Puts | ✓ | `POST /api/put-call/analyze` |
| Cached Data | ✓ | `GET /api/cache/contracts` |

Shared behavior across tabs:

- **4 × 2 tab grid** in the React UI (row 1 = contract tools, row 2 = scanners)
- **Sidebar contract form** for tabs 1–3 (ticker, Call/Put, MM/DD expiration, strike)
- **Fetch live data** toggle — `live_fetch=false` (default) = cache-only, no network
- **Disk cache** in `./.cache/` — same parquet/JSON store as the legacy Streamlit app
- **Watchlist** includes AAPL (Apple) alongside TSLA, NVDA, SPY, META, MSFT, AMZN, GOOGL, NFLX

---

## Architecture

```
StockForecastingOptions/
├── backend/
│   └── main.py           # FastAPI REST API
├── frontend/             # React + TypeScript + Plotly
├── services/             # Shared business logic (no UI)
│   ├── analytics.py      # Watchlist, SMA, PCR, weekly trend
│   ├── contract_service.py
│   ├── data_access.py
│   └── serialize.py
├── cache.py              # Disk-backed yfinance cache
├── forecasting.py        # Black-Scholes + four forecast models
├── app.py                # Legacy Streamlit UI (optional)
└── .cache/               # Parquet/JSON cache (created at runtime)
```

| Layer | Technology | Role |
|---|---|---|
| Frontend | React, TypeScript, Vite, Plotly | 8-tab dashboard, sidebar contract form |
| Backend | FastAPI, Pydantic, Uvicorn | JSON API |
| Services | pandas, numpy, scikit-learn, statsmodels | All calculations |
| Data | yfinance + `./.cache/` | Network + disk persistence |

---

## Dashboard tabs

The UI uses a **4 × 2 tab grid**:

| Row | Tabs |
|---|---|
| **1 — Contract** | Recent Activity · 5-Day Forecasts · What-If Scenario · Track the Best |
| **2 — Scanners** | Quick Summary · Check SMA · Calls vs Puts · Cached Data |

### Contract tabs (sidebar form required)

Fill in **ticker**, **Call/Put**, **expiration (MM/DD)**, **strike**, then click **Fetch Data**.

| Tab | What it shows |
|---|---|
| **Recent Activity** | Last 30 sessions for the option (OHLCV table + candlestick/volume chart). Underlying close aligned per day. 20-week MA weekly trend note. |
| **5-Day Forecasts** | Four models (Monte Carlo, candle patterns, ARIMA, Random Forest). Comparison table + per-model charts. Horizon capped at days to expiry. |
| **What-If Scenario** | Greeks panel, Black-Scholes reprice, P&L attribution, sensitivity chart, price grid for a target underlying price/date/IV. |

### Scanner tabs (work independently)

| Tab | What it shows |
|---|---|
| **Track the Best** | Daily % movers for a fixed watchlist: TSLA, NVDA, SPY, META, MSFT, AAPL, AMZN, GOOGL, NFLX. Losers on top, gainers below. Own **Fetch live data** toggle. |
| **Quick Summary** | 50-day and 200-day SMA table for the watchlist. Above/below labels and overall trend. |
| **Check SMA** | Enter any ticker(s) (comma-separated). Vertical metric table + weekly trend blocks. |
| **Calls vs Puts** | Call vs put volume and open interest for a ticker + expiration (default SPY). Put/call ratio, bar chart, top strikes by volume. Use `^SPX` for index options. |
| **Cached Data** | Browse option contracts on disk. View last 30 sessions + chart. **Load into sidebar form** to run forecasts/what-if without retyping. |

---

## Sidebar inputs

| Field | Example | Notes |
|---|---|---|
| Stock ticker | `AAPL`, `SPY`, `^SPX` | Index options need the caret (`^SPX`) |
| Option type | Call / Put | |
| Expiration | `06/20` | MM/DD — year resolved to nearest listed expiration |
| Strike | `150.0` | Must match chain exactly |
| Fetch live data | off (default) | See [Caching](#caching) below |

---

## REST API

Base URL: `http://127.0.0.1:8000`

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/watchlist` | Watchlist symbols |
| GET | `/api/watchlist/movers?live_fetch=false` | Track the Best |
| GET | `/api/watchlist/summary?live_fetch=false` | Quick Summary |
| POST | `/api/sma/check` | Check SMA — body: `{ "tickers": "NVDA, AAPL", "live_fetch": false }` |
| POST | `/api/put-call/analyze` | Calls vs Puts — body: `{ "ticker": "SPY", "expiration_mmdd": "06/20", "live_fetch": false }` |
| POST | `/api/contract/lookup` | Contract + 30 sessions — body: `{ "ticker", "option_type", "expiration_mmdd", "strike", "live_fetch" }` |
| POST | `/api/contract/forecasts` | Four forecast models (same body as lookup) |
| POST | `/api/contract/what-if` | Scenario — lookup fields + `target_price`, `target_mmdd`, `scenario_iv_pct` |
| GET | `/api/cache/summary` | Cache file count and size |
| GET | `/api/cache/contracts` | List cached option contracts |
| GET | `/api/cache/contracts/{symbol}` | One contract's cached history |
| POST | `/api/cache/clear` | Wipe cache — body: `{ "confirm": true, "symbol": null }` |

Errors return JSON: `{ "detail": { "code", "message", "details" } }`.

---

## Forecast models

All four approaches forecast the **underlying first**, then revalue the option via **Black-Scholes** (theta decay included).

| Model | Method |
|---|---|
| **A. Monte Carlo + BS** | 5,000 GBM paths; 10/50/90 percentile option price cone |
| **B. Candlestick patterns** | Doji, Hammer, Engulfing, etc.; conditional forward returns |
| **C. ARIMA(1,1,1)** | Log-price ARIMA with 80% confidence band |
| **D. Random Forest** | Lag returns, RSI, MACD, ATR, candle ratios (needs ≥80 days) |

---

## Caching

The app uses a **disk cache** in `./.cache/` plus an explicit **`live_fetch`** flag on every data endpoint / UI toggle.

| Mode | `live_fetch` | Behavior |
|---|---|---|
| **Cache-only** | `false` (default) | Reads only from disk. **No network calls.** If nothing is cached, the UI shows *No cached data — check **Fetch live data***. |
| **Live** | `true` | Downloads or refreshes from Yahoo Finance and saves to `./.cache/`. |

### What is cached

| Type | Format | Incremental? |
|---|---|---|
| OHLCV (contracts + underlyings) | Parquet | Yes — daily delta when live |
| Option expirations | JSON | Snapshot refresh when live |
| Option chains (calls/puts) | Parquet pair | Snapshot refresh when live |

First live fetch bootstraps ~3 months for contracts and ~1 year for underlyings. Subsequent live calls pull only new bars when needed.

### Managing cache

- **React sidebar**: cache file count + **Clear all cached data** (with browser confirm).
- **API**: `POST /api/cache/clear` with `{ "confirm": true }`.
- **Manual**: delete `./.cache/` — next live fetch rebuilds it.

Add `.cache/` to `.gitignore` if you do not want cached data in git.

---

## Legacy Streamlit UI

The original single-file UI still works:

```bash
source /Users/sriramsreedhar/WORK4/.venv/bin/activate
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions
streamlit run app.py
```

Opens at **http://localhost:8501**. Feature parity with the React app; caching behavior is the same.

---

## Notes & limitations

- Illiquid or new contracts may return empty history.
- `yfinance` can rate-limit or fail transiently — retry after a few seconds; cached data still works offline.
- Strikes must match the chain exactly; the app suggests nearest strikes on mismatch.
- Forecasts assume **constant volatility** (single-vol Black-Scholes).
- Random Forest needs ~80 days of underlying history.
- Risk-free rate is hardcoded at 4.5% in `forecasting.py` (`RISK_FREE_RATE`).

---

## Disclaimer

**Nothing in this app is financial advice.** The forecasts are statistical tools for exploration only. Do not trade based on these outputs.

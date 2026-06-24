# Tech Stack — Options Lookup

Stock options dashboard: contract history, forecasts, Greeks what-if, watchlist scanners, SMA tools, put/call analysis, and cached contracts.

**Primary UI:** React + FastAPI  
**Data source:** Yahoo Finance via [`yfinance`](https://github.com/ranaroussi/yfinance)

---

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  React 19 + TypeScript + Vite + Plotly.js    :5173         │
└───────────────────────────┬─────────────────────────────────┘
                            │  HTTP  /api/*  (Vite dev proxy)
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI + Uvicorn + Pydantic                  :8000         │
│  backend/main.py                                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  services/          Business logic (UI-agnostic)             │
│  cache.py           Disk cache + live_fetch gate             │
│  forecasting.py     Black-Scholes, forecasts, Greeks           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  ./.cache/          Parquet (OHLCV, chains) + JSON (exps)    │
│  yfinance           Yahoo Finance (only when live_fetch=true)│
└─────────────────────────────────────────────────────────────┘
```

---

## Frontend

| Category | Technology | Version (approx.) | Role |
|----------|------------|-------------------|------|
| UI framework | **React** | 19.x | Component-based dashboard |
| Language | **TypeScript** | 6.x | Type-safe UI code |
| Build tool | **Vite** | 8.x | Dev server, HMR, production build |
| Charts | **Plotly.js** + **react-plotly.js** | 3.x / 4.x | Candlesticks, forecast lines, bar charts |
| Lint | **Oxlint** | 1.x | Fast JS/TS linting |
| Dev server | Vite `@ :5173` | — | Proxies `/api` → backend `:8000` |

### Frontend layout

```
frontend/
├── src/
│   ├── App.tsx                 Main shell, tab grid, sidebar wiring
│   ├── api.ts                  Fetch wrapper + typed API client
│   ├── types.ts                Shared TS interfaces
│   └── components/
│       ├── Sidebar.tsx         Contract form + Fetch live data toggle
│       ├── TabPanels.tsx       All 8 tab UIs
│       ├── PriceChart.tsx      Plotly candlestick + volume
│       ├── DataTable.tsx       Session / summary tables
│       └── DataModeBanner.tsx  Cache-only vs live mode indicator
├── vite.config.ts              API proxy to port 8000
└── package.json
```

---

## Backend

| Category | Technology | Version (approx.) | Role |
|----------|------------|-------------------|------|
| API framework | **FastAPI** | 0.115+ | REST endpoints, OpenAPI docs |
| ASGI server | **Uvicorn** | 0.32+ | Runs the API (`--reload` in dev) |
| Validation | **Pydantic** | 2.9+ | Request/response schemas |
| Entry point | `backend/main.py` | — | Routes, CORS, error mapping |

### API surface (summary)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/contract/lookup` | Resolve contract + last 30 sessions |
| POST | `/api/contract/forecasts` | Four forecast models |
| POST | `/api/contract/what-if` | Greeks + scenario reprice |
| GET | `/api/watchlist/movers` | Track the Best |
| GET | `/api/watchlist/summary` | Quick Summary (50/200 SMA) |
| POST | `/api/sma/check` | Check SMA (any tickers) |
| POST | `/api/put-call/analyze` | Calls vs Puts |
| GET | `/api/cache/contracts` | Cached Data browser |
| POST | `/api/cache/clear` | Wipe disk cache |

Interactive docs: **http://127.0.0.1:8000/docs**

---

## Services layer (Python)

Shared logic used by FastAPI (and optionally Streamlit). No UI dependencies.

| Module | Responsibility |
|--------|----------------|
| `services/analytics.py` | Watchlist movers, SMA tables, put/call stats, weekly trend notes |
| `services/contract_service.py` | Contract lookup, forecasts orchestration, what-if scenarios |
| `services/data_access.py` | Thin wrappers over `cache.py` |
| `services/serialize.py` | pandas → JSON for API responses |
| `services/messages.py` | Cache-miss / live-fetch user messages |

---

## Data & analytics (Python)

| Library | Role |
|---------|------|
| **yfinance** | Option chains, expirations, OHLCV from Yahoo Finance |
| **pandas** | Tables, time series, SMA/rolling calcs |
| **NumPy** | Numerical arrays |
| **SciPy** | Normal CDF (Black-Scholes) |
| **statsmodels** | ARIMA(1,1,1) forecasts |
| **scikit-learn** | Random Forest next-day return model |

### `forecasting.py`

| Feature | Method |
|---------|--------|
| Option pricing | Black-Scholes (vectorized) |
| Greeks | Delta, Gamma, Theta, Vega, Rho |
| What-if | `scenario_price` — Greek attribution + BS reprice |
| Forecast A | Monte Carlo + BS (5,000 paths) |
| Forecast B | Candlestick pattern conditional stats |
| Forecast C | ARIMA on log prices |
| Forecast D | Random Forest on engineered features |

---

## Caching

| Component | Format | Location |
|-----------|--------|----------|
| OHLCV (stocks + option contracts) | Parquet | `./.cache/*.parquet` |
| Option expirations | JSON | `./.cache/*__expirations.json` |
| Option chains (calls/puts) | Parquet pair | `./.cache/*__chain_*_{calls,puts}.parquet` |

| Mode | Flag | Behavior |
|------|------|----------|
| Cache-only | `live_fetch=false` (default) | Disk read only — **no network** |
| Live | `live_fetch=true` | Refresh from Yahoo; OHLCV uses incremental delta fetch |

---

## Legacy UI (optional)

| Category | Technology | Role |
|----------|------------|------|
| UI | **Streamlit** | Original single-file app (`app.py`) |
| Charts | **Plotly** (Python) | In-app charts |

Run: `streamlit run app.py` → **http://localhost:8501**

Same `cache.py` and `forecasting.py` power both UIs.

---

## Runtime & tooling

| Item | Details |
|------|---------|
| Python | 3.11+ recommended |
| Virtual env | `/Users/sriramsreedhar/WORK4/.venv` |
| Node.js | 18+ for frontend |
| Startup | `./start.sh` — activates venv, starts API + Vite, prints UI URL |
| Dependencies | `requirements.txt` (Python), `frontend/package.json` (Node) |

### Ports

| Service | URL |
|---------|-----|
| React UI | http://localhost:5173 |
| FastAPI | http://127.0.0.1:8000 |
| API docs | http://127.0.0.1:8000/docs |
| Streamlit (legacy) | http://localhost:8501 |

---

## Project tree (high level)

```
StockForecastingOptions/
├── backend/              FastAPI app
├── frontend/             React + Vite app
├── services/             Shared Python business logic
├── cache.py              Disk cache + yfinance gate
├── forecasting.py        Models & Black-Scholes
├── app.py                Legacy Streamlit UI
├── start.sh              One-command dev startup
├── requirements.txt      Python dependencies
├── README.md             Setup & features guide
└── Tech-Stack.md         This file
```

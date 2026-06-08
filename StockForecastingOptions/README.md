# Options Lookup

A Streamlit web app that fetches the **last 30 trading sessions** for a
specific stock option contract and offers **four next-5-day forecast
approaches**, all powered by free Yahoo Finance data via `yfinance`.

## Inputs

- **Stock Ticker** — e.g. `AAPL`, `TSLA`, `SPY`
- **Option Type** — Call or Put
- **Expiration (MM/DD)** — e.g. `06/26`. The year is auto-resolved to the
  nearest matching listed expiration.
- **Strike Price** — e.g. `150.0`

## Output

### Section 1 — Last 30 trading sessions

- Summary header (last price, implied volatility, open interest)
- Formatted table (Open / High / Low / Close / Volume)
- Interactive Plotly chart: candlestick + close line + volume bars, with
  unified hover tooltips

### Section 2 — Forecasts (next 5 trading days)

Four independent statistical models. **All forecast the underlying first and
then revalue the option using Black-Scholes**, so the option's theta decay is
captured.

| Approach | What it does |
|---|---|
| **A. Monte Carlo + Black-Scholes** | 5,000 GBM paths of the underlying using historical drift and the option's implied vol (or 30-day realized as fallback). Each path is BS-revalued each day to produce a 10/50/90 percentile **projection cone** on the option price. |
| **B. Candlestick patterns** | Detects Doji, Hammer, Shooting Star, Bullish/Bearish Engulfing, Morning/Evening Star on the underlying's 1-year history. Shows historical conditional 5-day return stats (count, mean, median, win rate). When the most recent bar matches a pattern, derives a single-point option-price forecast via BS. |
| **C. ARIMA(1,1,1)** | Fits an ARIMA model to the underlying's log prices, produces a mean forecast with an 80% confidence band, and BS-revalues for the option. |
| **D. Random Forest** | Trains on engineered features (lag returns, RSI, MACD, ATR, body/wick ratios, volume) to predict next-day returns, then iteratively rolls 5 days forward. BS-revalued for the option. |

A **comparison table** at the top of the Forecasts section shows the day-5
option price (and confidence bands where applicable) from each approach
side-by-side. Per-approach detail tabs include forecast charts overlaid on the
option's recent history.

### Section 4 — Cached Data (browse previously-fetched contracts)

A standalone tab — works independently of the contract form — that lists
every option contract you've previously fetched (and still have on disk),
parses each OCC symbol, and lets you re-view the data without any network
call.

For each cached contract you'll see:

- A summary table with **Ticker / Type / Strike / Expiration / Rows / Last bar
  / Cached on / Size**
- A drop-down to pick one
- The contract's last 30 sessions (with the highest/lowest underlying-stock
  close highlighted blue/red, same as Recent Activity)
- A candlestick + close-line + volume chart
- A **Load this contract into the sidebar form** button — pre-fills the form
  inputs for that contract so you can run forecasts or What-If on it without
  retyping a thing

This is the simplest way to revisit anything you've already pulled, and it's
fully cache-only by design — no Yahoo Finance calls.

### Section 5 — Track the Best (watchlist movers)

A standalone tab — works independently of the contract form — that shows
today's biggest moves across a fixed watchlist:

> Tesla, NVIDIA, S&P 500 (SPY), Meta, Microsoft, Amazon, Google, Netflix

For each ticker, the app computes the percent change between yesterday's close
and the latest close, then sorts the results into two side-by-side columns:

- **📈 What went up today** — gainers, sorted high-to-low
- **📉 What went down today** — losers, sorted low-to-high

Each line is rendered in plain English, e.g.:

> **Tesla** (TSLA) went up **+5.20%** and last closed at **$420.50**
> Previous close: $399.71  ·  Bar date: 2026-06-06

The tab has its **own** *Fetch live data for watchlist* checkbox (separate
from the global one) and a **Refresh now** button so you control exactly
when the watchlist queries Yahoo Finance.

## How to run this app

### Project layout

The virtual environment and the app code live in **separate** directories:

```
/Users/sriramsreedhar/WORK4/
├── .venv/                          ← virtual environment (one level up)
└── StockForecastingOptions/        ← app code (this folder)
    ├── app.py
    ├── forecasting.py
    ├── requirements.txt
    └── README.md
```

This is why the run instructions below `cd` into
`StockForecastingOptions` but activate the venv from the parent.

### One-time setup (first run only)

```bash
cd /Users/sriramsreedhar/WORK4
python3 -m venv .venv
source .venv/bin/activate
pip install -r StockForecastingOptions/requirements.txt
```

### Every time you want to start the app

```bash
source /Users/sriramsreedhar/WORK4/.venv/bin/activate
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions
streamlit run app.py
```

You should see your shell prompt change to show `(.venv)` — that confirms the
virtual environment is active. The app will open in your browser at
[http://localhost:8501](http://localhost:8501). Press `Ctrl+C` in the terminal
to stop the server.

> **Important paths to remember:**
>
> - The activate script is at `/Users/sriramsreedhar/WORK4/.venv/bin/activate`
>   (in the parent directory, **not** inside `StockForecastingOptions`).
> - `app.py` is at `/Users/sriramsreedhar/WORK4/StockForecastingOptions/app.py`,
>   so `streamlit run app.py` must be invoked from inside that folder.
> - Do **not** `cd` into `.venv` itself before activating — the activate path
>   is relative to its parent.

### Optional: one-line shortcut

If you don't want to type all that each time, add this alias to your
`~/.zshrc`:

```bash
alias runforecast='source /Users/sriramsreedhar/WORK4/.venv/bin/activate && cd /Users/sriramsreedhar/WORK4/StockForecastingOptions && streamlit run app.py'
```

Then reload (`source ~/.zshrc`) and just run `runforecast` from anywhere.

### Alternative: run without the venv

If the system Python 3.12 already has the dependencies installed
system-wide, you can skip activation:

```bash
cd /Users/sriramsreedhar/WORK4/StockForecastingOptions
streamlit run app.py
```

If you see `ModuleNotFoundError: No module named 'plotly'` (or any other
package), the system Python is missing dependencies — use the venv path
above instead.

### Stopping & deactivating

- Stop the Streamlit server: `Ctrl+C` in the terminal where it's running
- Exit the venv: `deactivate`

## Files

- `app.py` — Streamlit UI, data fetching, charts, and Forecasts section
- `forecasting.py` — Black-Scholes, volatility estimation, and the four forecast
  implementations (Monte Carlo, candle patterns, ARIMA, Random Forest)
- `cache.py` — disk-backed incremental OHLCV cache (parquet)
- `requirements.txt` — pinned dependencies

## Caching (rate-limit friendly)

The app uses a **layered cache** so you don't hit Yahoo Finance on every
interaction, plus an explicit user-controlled **"Fetch live data"** toggle so
you can decide *when* (or whether) to call Yahoo Finance at all:

| Layer | What it caches | TTL | Persists across restarts? | Incremental? |
|---|---|---|---|---|
| Streamlit memory | All fetches | 15 min – 24 h | No | No |
| Disk parquet (`./.cache/`) | OHLCV history (option contract + underlying), option chains | until cleared | **Yes** | **OHLCV: yes — only the daily delta is fetched** |
| Disk JSON (`./.cache/`) | Expirations lists | until cleared | **Yes** | Snapshot — refreshed when live mode is on |

### "Fetch live data" toggle (sidebar)

A checkbox at the top of the sidebar — labelled **"Fetch live data from Yahoo
Finance"** — controls whether the app is allowed to make network calls.

| Mode | Behavior | Use it when |
|---|---|---|
| **Cache-only** (default, unchecked) | Reads ONLY from `./.cache/`. **Zero** network calls. Returns whatever was cached on a previous run. Friendly warnings appear if a requested ticker/contract isn't cached yet. | You want the fastest possible UI, no rate-limit risk, and you trust the data is recent enough for what you're exploring. |
| **Live** (checkbox checked) | Refreshes the disk cache: fetches the daily delta of OHLCV, re-pulls the expirations list and option chain. | You want the latest market data — typically once at the start of a session, then turn it back off. |

The current data freshness is shown right below the contract metrics:

> :package: Data updated: 2026-06-06 22:58 · Last bar: 2026-06-05 · Mode: **cache only**

If you switch to live mode the badge turns green (:satellite:) and the
timestamp updates as the cache is refreshed.

### How the OHLCV disk cache works

On first call for a symbol (with live mode ON), the app fetches a baseline
(3 months for option contracts, 1 year for underlyings) and saves it as a
parquet file in `./.cache/`. On subsequent live-mode calls, the cache is
loaded from disk, the **last cached date is checked**, and yfinance is queried
for **only the delta** (one or two new days, in most cases). If the cache is
already up to date through the last business day, **no network call is made at
all** — even in live mode.

In cache-only mode the disk file is read directly and yfinance is never
contacted, regardless of how stale the data is.

This means:

- After the first run, even live mode only sends a tiny incremental request per business day
- The app stays responsive even offline — disk reads are <50 ms
- Yahoo Finance is happy: total daily requests are O(distinct symbols), not
  O(page interactions × distinct symbols)

### Managing the cache

In the sidebar, expand **"Cache settings"** to see:

- The exact cache directory (`./.cache/` next to `app.py`)
- The number of cached files and total size on disk
- A list of **recently-updated cached symbols** with their last cache-write
  timestamp and last bar date — so you can verify exactly how stale each
  symbol's data is
- A **"Clear all cached data"** button that wipes both the disk cache and the
  Streamlit in-memory cache

The cache directory is safe to delete at any time — the next fetch (in live
mode) will rebuild it. Add `.cache/` to your `.gitignore` if you don't want
to commit cached data.

## Notes & limitations

- Some option contracts have no recent trading volume; in that case the history
  endpoint returns no rows and the app surfaces a friendly warning.
- yfinance occasionally rate-limits or returns transient errors. If a fetch
  fails, wait a few seconds and try again. The disk cache makes recovery much
  faster — already-cached data continues to work even when fresh fetches fail.
- Strikes must match exactly. If the strike you entered isn't listed for the
  contract, the app shows the nearest available strikes.
- Forecasts use **constant volatility** (single-vol Black-Scholes). Real markets
  have skew, term structure, regime changes, jumps around earnings, and many
  other dynamics not captured here.
- The Random Forest model needs at least ~80 days of underlying history to
  train. Newly-listed tickers will skip approach D.
- Risk-free rate is hardcoded at 4.5% (`fc.RISK_FREE_RATE` in `forecasting.py`).
  Adjust if needed.

## Disclaimer

**Nothing in this app is financial advice.** The forecasts are statistical toys
intended for exploration only. Do not trade based on these outputs.


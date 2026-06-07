# Options Lookup

A Streamlit web app that fetches the **last 10 trading sessions** for a
specific stock option contract and offers **four next-5-day forecast
approaches**, all powered by free Yahoo Finance data via `yfinance`.

## Inputs

- **Stock Ticker** — e.g. `AAPL`, `TSLA`, `SPY`
- **Option Type** — Call or Put
- **Expiration (MM/DD)** — e.g. `06/26`. The year is auto-resolved to the
  nearest matching listed expiration.
- **Strike Price** — e.g. `150.0`

## Output

### Section 1 — Last 10 trading sessions

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
- `requirements.txt` — pinned dependencies

## Notes & limitations

- Some option contracts have no recent trading volume; in that case the history
  endpoint returns no rows and the app surfaces a friendly warning.
- yfinance occasionally rate-limits or returns transient errors. If a fetch
  fails, wait a few seconds and try again. Lookups are cached for 5 minutes.
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


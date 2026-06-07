"""Options Lookup — Streamlit app.

Takes a stock ticker, option type (Call/Put), expiration date in MM/DD format,
and a strike price, then displays the last 30 trading sessions for that
specific option contract as both a table and an interactive Plotly chart.

Also offers four next-5-day forecast approaches in a Forecasts section:
  A. Monte Carlo + Black-Scholes (projection cone)
  B. Candlestick pattern recognition + conditional historical stats
  C. ARIMA forecast on the underlying
  D. Random Forest on engineered features
"""

from __future__ import annotations

import re
import textwrap
from datetime import date, datetime
from typing import List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

import forecasting as fc

st.set_page_config(
    page_title="Options Lookup",
    page_icon="📈",
    layout="wide",
)

MMDD_RE = re.compile(r"^\d{2}/\d{2}$")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=300, show_spinner=False)
def get_expirations(ticker: str) -> List[str]:
    """Return the list of option expiration dates ('YYYY-MM-DD') for a ticker."""
    return list(yf.Ticker(ticker).options or [])


@st.cache_data(ttl=300, show_spinner=False)
def get_option_chain(ticker: str, expiration: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (calls, puts) DataFrames for the given ticker + expiration."""
    chain = yf.Ticker(ticker).option_chain(expiration)
    return chain.calls, chain.puts


@st.cache_data(ttl=300, show_spinner=False)
def get_contract_history(contract_symbol: str) -> pd.DataFrame:
    """Fetch ~3 months of OHLCV for a specific option contract symbol.

    The display table shows the most recent 30 trading sessions; we fetch
    a buffer to handle weekends/holidays and any thin-trading days.
    """
    return yf.Ticker(contract_symbol).history(period="3mo")


@st.cache_data(ttl=600, show_spinner=False)
def get_underlying_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch underlying OHLCV history for the given ticker."""
    df = yf.Ticker(ticker).history(period=period)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def resolve_expiration(mm: int, dd: int, available: List[str]) -> str:
    """Map MM/DD to the soonest matching real expiration date.

    Searches the available expirations for one whose month/day match the input.
    If multiple match across years, returns the earliest one that is today or
    later. Raises ValueError if nothing matches.
    """
    today = date.today()
    matches: List[date] = []
    for s in available:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        if d.month == mm and d.day == dd:
            matches.append(d)

    if not matches:
        raise ValueError("no_match")

    future = [d for d in matches if d >= today]
    chosen = min(future) if future else max(matches)
    return chosen.strftime("%Y-%m-%d")


def nearest_expirations(available: List[str], n: int = 5) -> List[str]:
    """Return the next n upcoming expirations from today (or last n if all past)."""
    today = date.today()
    parsed = [datetime.strptime(s, "%Y-%m-%d").date() for s in available]
    upcoming = sorted(d for d in parsed if d >= today)
    if upcoming:
        return [d.strftime("%m/%d/%Y") for d in upcoming[:n]]
    return [d.strftime("%m/%d/%Y") for d in sorted(parsed)[-n:]]


def format_volume(v) -> str:
    if pd.isna(v):
        return "-"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


# --------------------------------------------------------------------------- #
# Sidebar form
# --------------------------------------------------------------------------- #
st.sidebar.title("Contract Inputs")

with st.sidebar.form("contract_form"):
    ticker_input = st.text_input("Stock Ticker", value="AAPL", help="e.g. AAPL, TSLA, SPY")
    option_type = st.radio("Option Type", ["Call", "Put"], horizontal=True)
    expiration_input = st.text_input(
        "Expiration (MM/DD)",
        value="",
        help="e.g. 06/26 — year is auto-resolved to the next listed expiration",
    )
    strike_input = st.number_input(
        "Strike Price",
        min_value=0.0,
        value=150.0,
        step=0.5,
        format="%.2f",
    )
    submitted = st.form_submit_button("Fetch Data", use_container_width=True)


# --------------------------------------------------------------------------- #
# Main panel
# --------------------------------------------------------------------------- #
st.title("Stock Options Dashboard")
st.caption(
    "Enter a ticker, option type, expiration (MM/DD) and strike on the left, "
    "then click **Fetch Data**. Three tabs below: recent activity, 5-day "
    "forecasts, and a Greeks-based what-if calculator. "
    "Data is sourced from Yahoo Finance via yfinance."
)

# Persist last-submitted form values across reruns so What-If widgets don't
# wipe the page. Validate freshly-submitted values, then store them.
if submitted:
    ticker = ticker_input.strip().upper()
    if not ticker:
        st.error("Please enter a stock ticker.")
        st.stop()

    if not MMDD_RE.match(expiration_input.strip()):
        st.error("Expiration must be in MM/DD format (e.g. `06/26`).")
        st.stop()

    mm, dd = (int(x) for x in expiration_input.strip().split("/"))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        st.error("Expiration MM/DD has an invalid month or day.")
        st.stop()

    strike = float(strike_input)
    if strike <= 0:
        st.error("Strike price must be greater than zero.")
        st.stop()

    st.session_state["fetch_inputs"] = {
        "ticker": ticker,
        "option_type": option_type,
        "expiration_input": expiration_input.strip(),
        "mm": mm,
        "dd": dd,
        "strike": strike,
    }

if "fetch_inputs" not in st.session_state:
    st.info("Fill in the form on the left and click **Fetch Data** to get started.")
    st.stop()

_inputs = st.session_state["fetch_inputs"]
ticker = _inputs["ticker"]
option_type = _inputs["option_type"]
expiration_input = _inputs["expiration_input"]
mm = _inputs["mm"]
dd = _inputs["dd"]
strike = _inputs["strike"]

# 2. Look up available expirations ---------------------------------------- #
with st.spinner(f"Looking up option expirations for {ticker}…"):
    try:
        expirations = get_expirations(ticker)
    except Exception as exc:  # noqa: BLE001 — surface any yfinance error to user
        st.error(f"Could not fetch options for `{ticker}`: {exc}")
        st.stop()

if not expirations:
    st.error(
        f"`{ticker}` has no listed options on Yahoo Finance. "
        "Double-check the ticker symbol."
    )
    st.stop()

# 3. Resolve MM/DD -> full date ------------------------------------------- #
try:
    expiration_date = resolve_expiration(mm, dd, expirations)
except ValueError:
    upcoming = nearest_expirations(expirations)
    st.error(
        f"No expiration matches **{expiration_input}** for `{ticker}`. "
        "Nearest upcoming expirations: " + ", ".join(f"`{d}`" for d in upcoming)
    )
    st.stop()

# 4. Pull option chain and find the contract ------------------------------ #
with st.spinner(f"Loading {option_type.lower()}s chain for {expiration_date}…"):
    try:
        calls, puts = get_option_chain(ticker, expiration_date)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load option chain: {exc}")
        st.stop()

chain_df = calls if option_type == "Call" else puts
match = chain_df[chain_df["strike"].round(4) == round(strike, 4)]

if match.empty:
    available_strikes = sorted(chain_df["strike"].unique().tolist())
    if available_strikes:
        nearest = min(available_strikes, key=lambda s: abs(s - strike))
        nearby = [s for s in available_strikes if abs(s - strike) <= 25][:10]
        st.error(
            f"Strike **{strike:g}** not found for {ticker} {option_type.lower()} "
            f"expiring {expiration_date}. Nearest available: **{nearest:g}**."
        )
        if nearby:
            st.write("Nearby strikes: " + ", ".join(f"`{s:g}`" for s in nearby))
    else:
        st.error("No strikes available in this option chain.")
    st.stop()

contract_symbol = match.iloc[0]["contractSymbol"]
last_price = match.iloc[0].get("lastPrice")
implied_vol = match.iloc[0].get("impliedVolatility")
open_interest = match.iloc[0].get("openInterest")

# 5. Header summary ------------------------------------------------------- #
st.subheader(f"{ticker} {option_type.upper()}  •  Strike {strike:g}  •  Exp {expiration_date}")
st.caption(f"Contract symbol: `{contract_symbol}`")

cols = st.columns(3)
cols[0].metric("Last Price", f"${last_price:.2f}" if pd.notna(last_price) else "—")
cols[1].metric(
    "Implied Vol",
    f"{implied_vol * 100:.2f}%" if pd.notna(implied_vol) else "—",
)
cols[2].metric(
    "Open Interest",
    format_volume(open_interest) if pd.notna(open_interest) else "—",
)

# 6. Fetch last 30 trading sessions --------------------------------------- #
with st.spinner("Fetching last 30 trading sessions…"):
    try:
        hist = get_contract_history(contract_symbol)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch contract history: {exc}")
        st.stop()

if hist is None or hist.empty:
    st.warning(
        "No historical price data available for this contract. "
        "It may be illiquid or newly listed. Try a different strike or expiration."
    )
    st.stop()

hist = hist.tail(30).copy()
hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index


# --------------------------------------------------------------------------- #
# Top-level tabbed layout
# --------------------------------------------------------------------------- #
tab_recent, tab_forecast, tab_whatif = st.tabs([
    "Recent Activity",
    "5-Day Forecasts",
    "What-If Scenario",
])

with tab_recent:
    # 7. Table ---------------------------------------------------------------- #
    st.markdown("### Last 30 Trading Sessions")
    st.caption(
        f"Open / High / Low / Close / Volume below are for the **option contract**. "
        f"The **{ticker} Close** column shows what the underlying stock closed at on that "
        "same day. The highest stock close is highlighted in "
        ":blue-background[**blue**] and the lowest in :red-background[**red**]."
    )

    # Pull the underlying stock's close prices for the same dates as `hist`
    stock_close_aligned = pd.Series(index=hist.index, dtype=float)
    try:
        underlying_recent = get_underlying_history(ticker, period="3mo")
        if underlying_recent is not None and not underlying_recent.empty:
            stock_close_aligned = underlying_recent["Close"].reindex(
                hist.index, method="ffill"
            )
    except Exception:
        pass  # column will show "—" via NaN handling below

    display_df = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    display_df.insert(0, "Date", display_df.index.strftime("%Y-%m-%d"))
    display_df["Stock Close"] = stock_close_aligned.values
    # Reorder so Stock Close sits right after the option's Close, before Volume
    display_df = display_df[
        ["Date", "Open", "High", "Low", "Close", "Stock Close", "Volume"]
    ].reset_index(drop=True)

    def _highlight_stock_close(col: pd.Series) -> list[str]:
        """Highlight the highest stock close blue and the lowest red."""
        valid = col.dropna()
        if valid.empty or valid.max() == valid.min():
            return [""] * len(col)
        col_max = valid.max()
        col_min = valid.min()
        styles = []
        for v in col:
            if pd.isna(v):
                styles.append("")
            elif v == col_max:
                styles.append(
                    "background-color: #1e88e5; color: white; font-weight: 600"
                )
            elif v == col_min:
                styles.append(
                    "background-color: #e53935; color: white; font-weight: 600"
                )
            else:
                styles.append("")
        return styles

    styled_df = (
        display_df.style
        .apply(_highlight_stock_close, subset=["Stock Close"])
        .format(
            {
                "Open": "${:,.2f}",
                "High": "${:,.2f}",
                "Low": "${:,.2f}",
                "Close": "${:,.2f}",
                "Stock Close": "${:,.2f}",
                "Volume": "{:,.0f}",
            },
            na_rep="—",
        )
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Date": st.column_config.TextColumn("Date"),
            "Open": st.column_config.NumberColumn("Option Open"),
            "High": st.column_config.NumberColumn("Option High"),
            "Low": st.column_config.NumberColumn("Option Low"),
            "Close": st.column_config.NumberColumn("Option Close"),
            "Stock Close": st.column_config.NumberColumn(
                f"{ticker} Close",
                help=(
                    f"{ticker}'s closing stock price on that day. "
                    "Highest = blue background, lowest = red background. "
                    "Use this to see how the option moved with the stock."
                ),
            ),
            "Volume": st.column_config.NumberColumn("Volume"),
        },
    )

    # 8. Interactive chart ---------------------------------------------------- #
    st.markdown("### Price Movement (hover for details)")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
        subplot_titles=("Price (Candlestick + Close)", "Volume"),
    )

    fig.add_trace(
        go.Candlestick(
            x=hist.index,
            open=hist["Open"],
            high=hist["High"],
            low=hist["Low"],
            close=hist["Close"],
            name="OHLC",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=hist.index,
            y=hist["Close"],
            mode="lines+markers",
            name="Close",
            line=dict(color="#42a5f5", width=2),
            marker=dict(size=6),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Close: $%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=hist.index,
            y=hist["Volume"],
            name="Volume",
            marker_color="#90a4ae",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Volume: %{y:,}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=620,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        row=2,
        col=1,
    )

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw history data"):
        st.dataframe(hist, use_container_width=True)


with tab_forecast:
    st.caption(
        "Four independent statistical models. None of these are financial advice; "
        "they are illustrative tools. All approaches forecast the underlying first "
        "and revalue the option via Black-Scholes."
    )

    with st.spinner("Loading 1 year of underlying price history…"):
        try:
            underlying = get_underlying_history(ticker, period="1y")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not fetch underlying history for `{ticker}`: {exc}")
            st.stop()

    if underlying is None or underlying.empty or len(underlying) < 60:
        st.warning(
            "Not enough underlying history to run forecasts (need ~60 trading days). "
            "Skipping the Forecasts section."
        )
        st.stop()

    spot = float(underlying["Close"].iloc[-1])
    today = pd.Timestamp(date.today())
    exp_ts = pd.Timestamp(expiration_date)
    T0 = fc.time_to_expiry_years(today, exp_ts)

    iv_for_model = float(implied_vol) if pd.notna(implied_vol) and implied_vol > 0 else None
    realized_vol = fc.historical_volatility(underlying["Close"], window=30)
    sigma = iv_for_model if iv_for_model is not None else realized_vol

    # Cap the forecast horizon at days remaining to expiry
    days_to_exp = max((exp_ts.normalize() - today.normalize()).days, 0)
    forecast_days = min(5, max(days_to_exp, 1))

    inp = fc.ForecastInputs(
        spot=spot,
        strike=strike,
        sigma=sigma,
        r=fc.RISK_FREE_RATE,
        T0_years=T0,
        option_type="call" if option_type == "Call" else "put",
        days=forecast_days,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Underlying spot", f"${spot:.2f}")
    c2.metric("Volatility used", f"{sigma * 100:.2f}%",
              help="Implied vol from option chain if available, else 30-day realized.")
    c3.metric("Time to expiry", f"{T0 * 365.25:.0f} days")
    c4.metric("Forecast horizon", f"{forecast_days} day(s)")

    if forecast_days < 5:
        st.info(
            f"Option expires in {days_to_exp} calendar day(s); forecast horizon "
            f"capped at {forecast_days}."
        )

    # --- Run all four approaches ----------------------------------------------- #
    with st.spinner("Running Monte Carlo + Black-Scholes…"):
        mc_df = fc.forecast_monte_carlo(underlying["Close"], inp, n_paths=5000)

    with st.spinner("Detecting candlestick patterns…"):
        patterns = fc.detect_candle_patterns(underlying)
        pattern_stats = fc.pattern_conditional_stats(underlying, patterns, horizon=forecast_days)
        pattern_fc = fc.forecast_from_patterns(underlying, inp)

    with st.spinner("Fitting ARIMA(1,1,1)…"):
        arima_df = fc.forecast_arima(underlying["Close"], inp)

    with st.spinner("Training Random Forest…"):
        rf_df = fc.forecast_random_forest(underlying, inp)

    current_opt_price = float(
        fc.black_scholes_price(spot, strike, T0, fc.RISK_FREE_RATE, sigma,
                               "call" if option_type == "Call" else "put")
    )

    # --- Summary comparison table --------------------------------------------- #
    st.markdown(f"### Day-{forecast_days} Option Price Forecast — Comparison")

    summary_rows = []
    summary_rows.append({
        "Approach": "A. Monte Carlo + BS",
        "Day-N option (median)": mc_df["o_p50"].iloc[-1],
        "Lower band": mc_df["o_p10"].iloc[-1],
        "Upper band": mc_df["o_p90"].iloc[-1],
        "Notes": "GBM, 5000 paths, BS revalued each step",
    })
    if pattern_fc is not None:
        summary_rows.append({
            "Approach": "B. Candlestick patterns",
            "Day-N option (median)": pattern_fc["predicted_option_price"],
            "Lower band": np.nan,
            "Upper band": np.nan,
            "Notes": f"After {pattern_fc['pattern']} (n={pattern_fc['n']})",
        })
    else:
        summary_rows.append({
            "Approach": "B. Candlestick patterns",
            "Day-N option (median)": np.nan,
            "Lower band": np.nan,
            "Upper band": np.nan,
            "Notes": "No pattern detected on the most recent bar",
        })
    if arima_df is not None:
        summary_rows.append({
            "Approach": "C. ARIMA(1,1,1)",
            "Day-N option (median)": arima_df["o_mean"].iloc[-1],
            "Lower band": arima_df["o_low"].iloc[-1],
            "Upper band": arima_df["o_high"].iloc[-1],
            "Notes": "80% confidence band on log prices",
        })
    else:
        summary_rows.append({
            "Approach": "C. ARIMA(1,1,1)",
            "Day-N option (median)": np.nan,
            "Lower band": np.nan,
            "Upper band": np.nan,
            "Notes": "ARIMA fit failed",
        })
    if rf_df is not None:
        summary_rows.append({
            "Approach": "D. Random Forest",
            "Day-N option (median)": rf_df["o_predicted"].iloc[-1],
            "Lower band": np.nan,
            "Upper band": np.nan,
            "Notes": "Iterated forward; lag returns + RSI/MACD/ATR + candle ratios",
        })
    else:
        summary_rows.append({
            "Approach": "D. Random Forest",
            "Day-N option (median)": np.nan,
            "Lower band": np.nan,
            "Upper band": np.nan,
            "Notes": "Insufficient training data",
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_df.insert(1, "Today", current_opt_price)

    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Today": st.column_config.NumberColumn(
                "Today", format="$%.2f",
                help="Option price right now (Black-Scholes at current spot, "
                     "current time-to-expiry, current IV).",
            ),
            "Day-N option (median)": st.column_config.NumberColumn(
                f"Day-{forecast_days} (most likely)", format="$%.2f",
                help="The middle estimate — half of the simulated futures end "
                     "above this, half end below. Best single-number guess.",
            ),
            "Lower band": st.column_config.NumberColumn(
                "Pessimistic", format="$%.2f",
                help="P10 — only 10% of simulated futures end below this. "
                     "Rough downside scenario.",
            ),
            "Upper band": st.column_config.NumberColumn(
                "Optimistic", format="$%.2f",
                help="P90 — only 10% of simulated futures end above this. "
                     "Rough upside scenario.",
            ),
        },
    )

    # --- Per-approach detailed tabs ------------------------------------------- #
    tab_a, tab_b, tab_c, tab_d = st.tabs([
        "A. Monte Carlo + BS",
        "B. Candle Patterns",
        "C. ARIMA",
        "D. Random Forest",
    ])

    # -- Tab A: Monte Carlo cone ----------------------------------------------- #
    with tab_a:
        st.markdown("**Monte Carlo + Black-Scholes** — 5,000 simulated futures, revalued via BS each day.")

        with st.expander("What do P10, P50, P90 mean?", expanded=False):
            st.markdown(textwrap.dedent("""
                Imagine we made **100 little pretend versions** of the future where the
                stock did slightly different things (because nobody knows for sure what
                will happen). We sort all 100 from worst to best, then look at three of them:

                | Label | What it is | Plain English |
                |---|---|---|
                | **P10** | The 10th-from-the-bottom outcome | The **pessimistic** scenario. Only 10 out of 100 ended worse than this. |
                | **P50** | The middle outcome (median) | The **most likely** middle result. Half are above, half below. |
                | **P90** | The 10th-from-the-top outcome | The **optimistic** scenario. Only 10 out of 100 ended better. |

                The shaded band on the chart goes from P10 to P90 — that's the **middle
                80% of all imagined futures**. So you can read it as:

                > *"There's about an 80% chance the price ends up somewhere in this band."*

                The other 20% (10% really pessimistic + 10% really optimistic) is outside
                the band. That's "tail risk" — surprise news, earnings shocks, etc.

                **Two flavors of P10/P50/P90 in the table below:**

                - **Stock (P10/P50/P90)** = forecast for the *underlying stock price* (e.g. NVDA)
                - **Option (P10/P50/P90)** = your option ticket's price *at* that stock price
                  (computed via Black-Scholes for each scenario)
            """).strip())

        last_idx = hist.index[-1] if not hist.empty else today
        future_dates = pd.bdate_range(start=last_idx + pd.Timedelta(days=1), periods=forecast_days)

        fig_a = go.Figure()
        fig_a.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"], mode="lines+markers", name="Option (history)",
            line=dict(color="#42a5f5", width=2),
        ))
        fig_a.add_trace(go.Scatter(
            x=future_dates, y=mc_df["o_p90"],
            name="Optimistic (P90)", mode="lines",
            line=dict(color="rgba(38,166,154,0.0)"),
            showlegend=False,
        ))
        fig_a.add_trace(go.Scatter(
            x=future_dates, y=mc_df["o_p10"],
            name="80% likely range (P10–P90)", mode="lines",
            fill="tonexty", fillcolor="rgba(38,166,154,0.18)",
            line=dict(color="rgba(38,166,154,0.0)"),
        ))
        fig_a.add_trace(go.Scatter(
            x=future_dates, y=mc_df["o_p50"],
            name="Most likely (median, P50)",
            mode="lines+markers", line=dict(color="#26a69a", width=2, dash="dash"),
        ))
        fig_a.update_layout(
            height=420, hovermode="x unified",
            title="Option price — history & forecast fan",
            margin=dict(l=10, r=10, t=40, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_a.update_yaxes(title_text="Option price (USD)")
        st.plotly_chart(fig_a, use_container_width=True)

        st.caption(
            "Hover the chart to see the price at each day. The shaded fan widens "
            "the further out you go — because the further into the future, the "
            "less certain we are."
        )

        mc_display = mc_df.copy()
        mc_display.insert(0, "Date", future_dates.strftime("%Y-%m-%d"))
        st.dataframe(
            mc_display,
            use_container_width=True, hide_index=True,
            column_config={
                "day": st.column_config.NumberColumn("Day"),
                "u_p10": st.column_config.NumberColumn(
                    "Stock — pessimistic", format="$%.2f",
                    help="P10: only 10 out of 100 simulated futures had the stock end below this.",
                ),
                "u_p50": st.column_config.NumberColumn(
                    "Stock — most likely", format="$%.2f",
                    help="P50 (median): the middle estimate for where the stock ends up.",
                ),
                "u_p90": st.column_config.NumberColumn(
                    "Stock — optimistic", format="$%.2f",
                    help="P90: only 10 out of 100 simulated futures had the stock end above this.",
                ),
                "o_p10": st.column_config.NumberColumn(
                    "Option — pessimistic", format="$%.2f",
                    help="P10: option ticket price in the pessimistic stock scenario "
                         "(BS-revalued at the P10 underlying).",
                ),
                "o_p50": st.column_config.NumberColumn(
                    "Option — most likely", format="$%.2f",
                    help="P50: middle estimate for the option ticket's price.",
                ),
                "o_p90": st.column_config.NumberColumn(
                    "Option — optimistic", format="$%.2f",
                    help="P90: option ticket price in the optimistic stock scenario.",
                ),
            },
        )

    # -- Tab B: Patterns ------------------------------------------------------- #
    with tab_b:
        st.markdown("**Candlestick patterns** — detected on the underlying over the past year.")
        recent = fc.latest_patterns(patterns, lookback=3)
        if recent:
            st.success("Recent patterns (last 3 sessions): " + ", ".join(recent))
        else:
            st.info("No notable candlestick patterns in the last 3 sessions.")

        if pattern_fc is not None:
            cA, cB, cC = st.columns(3)
            cA.metric("Pattern", pattern_fc["pattern"])
            cA.caption(f"n = {pattern_fc['n']} historical occurrences")
            cB.metric("Avg fwd return", f"{pattern_fc['mean_return_pct']:+.2f}%",
                      help=f"Underlying's average {forecast_days}-day return after this pattern")
            cB.caption(f"Win rate: {pattern_fc['win_rate_pct']:.1f}%")
            cC.metric("Implied option price",
                      f"${pattern_fc['predicted_option_price']:.2f}",
                      delta=f"{pattern_fc['predicted_option_price'] - current_opt_price:+.2f}")
            cC.caption("BS-revalued at predicted underlying")

        st.markdown("**Historical conditional stats** (past 1 year):")
        st.dataframe(
            pattern_stats,
            use_container_width=True, hide_index=True,
            column_config={
                "pattern": st.column_config.TextColumn("Pattern"),
                "count": st.column_config.NumberColumn("Occurrences"),
                "mean_return_pct": st.column_config.NumberColumn(
                    f"Mean {forecast_days}d ret %", format="%+.2f%%"),
                "median_return_pct": st.column_config.NumberColumn(
                    f"Median {forecast_days}d ret %", format="%+.2f%%"),
                "std_return_pct": st.column_config.NumberColumn("Std %", format="%.2f%%"),
                "win_rate_pct": st.column_config.NumberColumn("Win rate %", format="%.1f%%"),
            },
        )

    # -- Tab C: ARIMA ---------------------------------------------------------- #
    with tab_c:
        st.markdown("**ARIMA(1,1,1)** on the underlying's log prices, with 80% confidence band, "
                    "then BS-revalued for the option.")
        if arima_df is None:
            st.error("ARIMA fit did not converge for this series.")
        else:
            last_idx = hist.index[-1] if not hist.empty else today
            future_dates = pd.bdate_range(start=last_idx + pd.Timedelta(days=1), periods=forecast_days)

            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(
                x=hist.index, y=hist["Close"], mode="lines+markers", name="Option (history)",
                line=dict(color="#42a5f5", width=2),
            ))
            fig_c.add_trace(go.Scatter(
                x=future_dates, y=arima_df["o_high"], name="Optimistic", mode="lines",
                line=dict(color="rgba(255,167,38,0.0)"), showlegend=False,
            ))
            fig_c.add_trace(go.Scatter(
                x=future_dates, y=arima_df["o_low"],
                name="80% likely range", mode="lines",
                fill="tonexty", fillcolor="rgba(255,167,38,0.18)",
                line=dict(color="rgba(255,167,38,0.0)"),
            ))
            fig_c.add_trace(go.Scatter(
                x=future_dates, y=arima_df["o_mean"], name="ARIMA best guess",
                mode="lines+markers", line=dict(color="#ffa726", width=2, dash="dash"),
            ))
            fig_c.update_layout(
                height=420, hovermode="x unified",
                title="Option price — ARIMA forecast",
                margin=dict(l=10, r=10, t=40, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            fig_c.update_yaxes(title_text="Option price (USD)")
            st.plotly_chart(fig_c, use_container_width=True)

            arima_display = arima_df.copy()
            arima_display.insert(0, "Date", future_dates.strftime("%Y-%m-%d"))
            st.dataframe(
                arima_display,
                use_container_width=True, hide_index=True,
                column_config={
                    "day": st.column_config.NumberColumn("Day"),
                    "u_mean": st.column_config.NumberColumn(
                        "Stock — best guess", format="$%.2f",
                        help="ARIMA's middle estimate for the stock price.",
                    ),
                    "u_low": st.column_config.NumberColumn(
                        "Stock — pessimistic", format="$%.2f",
                        help="Lower edge of the 80% confidence band.",
                    ),
                    "u_high": st.column_config.NumberColumn(
                        "Stock — optimistic", format="$%.2f",
                        help="Upper edge of the 80% confidence band.",
                    ),
                    "o_mean": st.column_config.NumberColumn(
                        "Option — best guess", format="$%.2f",
                        help="Option ticket price at the best-guess stock price.",
                    ),
                    "o_low": st.column_config.NumberColumn(
                        "Option — pessimistic", format="$%.2f",
                    ),
                    "o_high": st.column_config.NumberColumn(
                        "Option — optimistic", format="$%.2f",
                    ),
                },
            )

    # -- Tab D: Random Forest -------------------------------------------------- #
    with tab_d:
        st.markdown("**Random Forest** on engineered features (lag returns, RSI, MACD, ATR, "
                    "candle body/wick ratios, volume), iterated forward.")
        if rf_df is None:
            st.error("Not enough training data (need ≥ 80 days of underlying history).")
        else:
            last_idx = hist.index[-1] if not hist.empty else today
            future_dates = pd.bdate_range(start=last_idx + pd.Timedelta(days=1), periods=forecast_days)

            fig_d = go.Figure()
            fig_d.add_trace(go.Scatter(
                x=hist.index, y=hist["Close"], mode="lines+markers", name="Option (history)",
                line=dict(color="#42a5f5", width=2),
            ))
            fig_d.add_trace(go.Scatter(
                x=future_dates, y=rf_df["o_predicted"], name="RF forecast",
                mode="lines+markers", line=dict(color="#ab47bc", width=2, dash="dash"),
            ))
            fig_d.update_layout(
                height=420, hovermode="x unified",
                title="Option price — Random Forest forecast",
                margin=dict(l=10, r=10, t=40, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            fig_d.update_yaxes(title_text="Option price (USD)")
            st.plotly_chart(fig_d, use_container_width=True)

            rf_display = rf_df.copy()
            rf_display.insert(0, "Date", future_dates.strftime("%Y-%m-%d"))
            st.dataframe(
                rf_display,
                use_container_width=True, hide_index=True,
                column_config={
                    "day": st.column_config.NumberColumn("Day"),
                    "u_predicted": st.column_config.NumberColumn(
                        "Stock (predicted)", format="$%.2f",
                        help="Random Forest's predicted stock price.",
                    ),
                    "o_predicted": st.column_config.NumberColumn(
                        "Option (predicted)", format="$%.2f",
                        help="Option ticket price at the predicted stock price (BS-revalued).",
                    ),
                },
            )


with tab_whatif:
    st.caption(
        "Pick a target underlying price and a target date, and see what this "
        "contract would be worth — both via the Delta/Gamma/Theta Taylor "
        "approximation and via a full Black-Scholes reprice. "
        "Hover anywhere on the sensitivity chart to read off the option price for "
        "any underlying price."
    )

    # --- Plain-English explainer (kid-friendly) ------------------------------ #
    with st.expander("New here? Click for a 30-second explainer", expanded=False):
        st.markdown(textwrap.dedent("""
            **What is this section doing?**

            Imagine an option is a **special ticket** that's worth different amounts of
            money depending on:

            1. The price of the stock
            2. How much time is left until the ticket expires
            3. How "jumpy" people think the stock will be

            This section lets you ask **"What if?"** questions like:

            > *"What if NVDA jumps to $215 by next Monday? How much will my ticket be worth?"*

            You'll see the answer **three ways**, but only **one is the real answer**:

            | Number | What it means | Like... |
            |---|---|---|
            | **Black-Scholes reprice** | The accurate answer. What the ticket would actually be worth. | Doing the full math problem with a calculator. |
            | Greeks-based estimate | A quick guess using shortcut numbers (Delta, Gamma, Theta). | Eyeballing where a thrown ball will land. |
            | Greeks − BS (residual) | How wrong the quick guess was. | The "oops" gap between guess and reality. |

            **Trust the Black-Scholes reprice.** That's the number Nasdaq, NYSE, and every
            major exchange use as their official price. The Greeks tell you the *story
            of why* the price changed — they're not the price itself.

            ---

            **What are these "Greeks"?**

            They're nicknames for "how much does the price change when ONE thing changes?"

            - **Delta** — If the stock goes up $1, how much does the option go up? (e.g. Delta = 0.5 → option goes up $0.50)
            - **Gamma** — How fast is Delta itself changing? (the curve)
            - **Theta** — How much value drips away each day, like ice melting? (always negative for buyers)
            - **Vega** — How much does the price change if the stock gets more "jumpy"?
            - **Rho** — How much does the price change if interest rates go up?

            You don't need to memorize these. The dashboard does the math for you.
        """).strip())

    # Default target date = next business day; cap at expiration
    default_target = today + pd.tseries.offsets.BDay(1)
    if default_target.date() > exp_ts.date():
        default_target = exp_ts
    default_target_mmdd = default_target.strftime("%m/%d")

    ws1, ws2, ws3 = st.columns([1, 1, 1])
    target_price = ws1.number_input(
        "Target underlying price ($)",
        min_value=0.01,
        value=float(round(spot, 2)),
        step=1.0,
        format="%.2f",
        key="whatif_target_price",
    )
    target_mmdd = ws2.text_input(
        "Target date (MM/DD)",
        value=default_target_mmdd,
        key="whatif_target_mmdd",
        help=f"Between today ({today.strftime('%m/%d')}) and expiration "
             f"({exp_ts.strftime('%m/%d')}).",
    )
    sigma_pct = ws3.slider(
        "Scenario IV (%) at target",
        min_value=1.0,
        max_value=200.0,
        value=float(round(sigma * 100, 2)),
        step=0.5,
        key="whatif_sigma_pct",
        help=f"Base IV: {sigma * 100:.2f}% (from chain or realized). "
             "Move the slider to apply a vol shock at the target date and see "
             "the vega contribution in the P&L attribution.",
    )
    base_sigma = sigma
    scenario_sigma = sigma_pct / 100.0
    sigma_used = scenario_sigma  # legacy alias for the sensitivity chart below

    # Parse target date
    if not MMDD_RE.match(target_mmdd.strip()):
        st.error("Target date must be in MM/DD format (e.g. `06/08`).")
        st.stop()

    t_mm, t_dd = (int(x) for x in target_mmdd.strip().split("/"))
    try:
        target_date = date(today.year, t_mm, t_dd)
        if target_date < today.date():
            target_date = date(today.year + 1, t_mm, t_dd)
    except ValueError:
        st.error(f"Invalid target date: {target_mmdd}")
        st.stop()

    target_ts = pd.Timestamp(target_date)
    if target_ts > exp_ts:
        st.warning(
            f"Target date {target_ts.strftime('%Y-%m-%d')} is after expiration "
            f"({exp_ts.strftime('%Y-%m-%d')}). Capping at expiration."
        )
        target_ts = exp_ts

    T_target = fc.time_to_expiry_years(target_ts, exp_ts)
    opt_type_short = "call" if option_type == "Call" else "put"

    # Run scenario
    scn = fc.scenario_price(
        spot=spot,
        strike=strike,
        T0_years=T0,
        T_target_years=T_target,
        r=fc.RISK_FREE_RATE,
        base_sigma=base_sigma,
        target_sigma=scenario_sigma,
        option_type=opt_type_short,
        target_S=float(target_price),
    )
    g = scn["greeks"]

    # --- Greeks panel --------------------------------------------------------- #
    st.markdown("### Current Greeks")
    st.caption(
        "Think of these as **shortcut numbers** that tell you how the option's "
        "price reacts when ONE thing changes. They explain *why* a price moves; "
        "they're not the price itself."
    )
    gc = st.columns(5)
    gc[0].metric(
        "Delta",
        f"{g['delta']:.4f}",
        help=(
            f"If the stock moves up $1, the option goes up about "
            f"**${g['delta']:.2f}** (and down by the same if it falls).\n\n"
            "Range: 0 to 1 for calls, 0 to −1 for puts."
        ),
    )
    gc[1].metric(
        "Gamma",
        f"{g['gamma']:.4f}",
        help=(
            f"How much Delta itself changes per $1 move in the stock. "
            f"Bigger Gamma = the option's sensitivity speeds up faster as the "
            f"stock moves. Gamma is highest near the strike price."
        ),
    )
    gc[2].metric(
        "Theta",
        f"${g['theta_per_day']:.4f}/day",
        help=(
            f"The option loses about **${abs(g['theta_per_day']):.2f} every "
            f"calendar day** just from time passing — like ice melting. "
            "Theta is the buyer's enemy and the seller's friend."
        ),
    )
    gc[3].metric(
        "Vega",
        f"${g['vega_per_pct']:.4f}/%",
        help=(
            f"If the stock gets 1% MORE jumpy (volatility ↑1pp), the option "
            f"price changes by about **${g['vega_per_pct']:+.2f}**. "
            "Big news, earnings, and crashes all push vega up."
        ),
    )
    gc[4].metric(
        "Rho",
        f"${g['rho_per_pct']:.4f}/%",
        help=(
            f"If interest rates go up by 1 percentage point, the option price "
            f"changes by about **${g['rho_per_pct']:+.2f}**. Usually small for "
            "short-dated options."
        ),
    )

    # --- Scenario summary ----------------------------------------------------- #
    st.markdown(
        f"### Scenario: `{ticker}` {option_type} @ {strike:g}, "
        f"underlying **${spot:.2f} → ${target_price:.2f}** "
        f"({target_price - spot:+.2f}) over **{scn['days_elapsed']:.0f} day(s)**"
    )

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric(
        "Current option price",
        f"${scn['current_price']:.2f}",
        help="What the option is worth right now (Black-Scholes priced at today's "
             "stock price, today's time-to-expiry, and base IV).",
    )
    sc2.metric(
        "Greeks shortcut estimate",
        f"${scn['greeks_estimate']:.2f}",
        delta=f"{scn['greeks_estimate'] - scn['current_price']:+.2f}",
        help=(
            "A QUICK GUESS using the Greeks: "
            "Current + Δ·ΔS + ½·Γ·ΔS² + Θ·Δt + Vega·Δσ. "
            "Fast but slightly off when the stock moves a lot. "
            "Traders use this for speed; risk systems use the full reprice (next column)."
        ),
    )
    sc3.metric(
        "★ Black-Scholes reprice",
        f"${scn['bs_reprice']:.2f}",
        delta=f"{scn['bs_reprice'] - scn['current_price']:+.2f}",
        help=(
            "★ **THE ACCURATE ANSWER.** Recomputes the option price from "
            "scratch with the new stock price, new time-to-expiry, and scenario IV. "
            "This is the value Nasdaq, NYSE, OCC, Bloomberg, and every major risk "
            "system treat as the source of truth. Trust this one."
        ),
    )
    diff = scn["greeks_estimate"] - scn["bs_reprice"]
    sc4.metric(
        "How off was the shortcut?",
        f"${diff:+.2f}",
        help=(
            "The gap between the shortcut (column 2) and the accurate answer "
            "(column 3). Small number = the shortcut worked well. "
            "Big number = the stock moved or vol shocked enough that "
            "higher-order curvature (Speed, Color, Vomma, Vanna, Charm) "
            "starts to matter."
        ),
    )

    # Plain-English verdict
    better_for_kid = scn["bs_reprice"]
    st.success(
        f"**Trust this number: ${better_for_kid:.2f}** — that's the Black-Scholes "
        "reprice (column 3 with the ★). It's what Nasdaq and NYSE use as the "
        "official theoretical price. The other columns just show *how* that price "
        "was put together from the Greeks. The 'How off was the shortcut?' column "
        "tells you whether the quick Greek-based guess was close or way off."
    )

    # --- P&L attribution waterfall (Nasdaq-style risk explain) --------------- #
    st.markdown("### Why did the price change? — Nasdaq-style breakdown")
    st.caption(
        "This chart shows **where the price change came from**. Think of it like "
        "a recipe: the option's price moved by a certain amount, and each Greek "
        "contributed its own ingredient. Green bars push the price up, red bars "
        "push it down. They all add up exactly to the Black-Scholes reprice — "
        "the accurate answer from above."
    )

    waterfall_components = [
        ("Starting price", scn["current_price"], "absolute"),
        ("From stock move (Delta)", scn["delta_pnl"], "relative"),
        ("From curve / convexity (Gamma)", scn["gamma_pnl"], "relative"),
        ("From time passing (Theta)", scn["theta_pnl"], "relative"),
        ("From volatility change (Vega)", scn["vega_pnl"], "relative"),
        ("Tiny leftover (higher-order)", scn["residual"], "relative"),
        ("★ Final accurate price", scn["bs_reprice"], "total"),
    ]

    fig_wf = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=[m for _, _, m in waterfall_components],
            x=[lbl for lbl, _, _ in waterfall_components],
            y=[val for _, val, _ in waterfall_components],
            text=[f"${val:+.2f}" if m == "relative" else f"${val:.2f}"
                  for _, val, m in waterfall_components],
            textposition="outside",
            connector={"line": {"color": "rgba(120,120,120,0.5)"}},
            increasing={"marker": {"color": "#26a69a"}},
            decreasing={"marker": {"color": "#ef5350"}},
            totals={"marker": {"color": "#42a5f5"}},
        )
    )
    fig_wf.update_layout(
        height=420,
        title=(
            f"Current ${scn['current_price']:.2f} → BS reprice ${scn['bs_reprice']:.2f}  "
            f"(ΔP = ${scn['bs_reprice_change']:+.2f})"
        ),
        margin=dict(l=10, r=10, t=50, b=10),
        yaxis_title="Option price ($)",
        showlegend=False,
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # Detail table
    st.markdown("**Attribution detail**")
    attribution_total = scn["attributed"] + scn["residual"]
    pnl_df = pd.DataFrame(
        [
            {"Component": "Delta · ΔS",
             "Formula": f"{g['delta']:.4f} × {scn['dS']:+.2f}",
             "Contribution": scn["delta_pnl"],
             "% of ΔP": (scn["delta_pnl"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "½ · Gamma · ΔS²",
             "Formula": f"0.5 × {g['gamma']:.4f} × ({scn['dS']:+.2f})²",
             "Contribution": scn["gamma_pnl"],
             "% of ΔP": (scn["gamma_pnl"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "Theta · days",
             "Formula": f"{g['theta_per_day']:.4f} × {scn['days_elapsed']:.0f}",
             "Contribution": scn["theta_pnl"],
             "% of ΔP": (scn["theta_pnl"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "Vega · Δσ",
             "Formula": f"{g['vega_per_pct']:.4f} × {scn['dsigma'] * 100:+.2f}pp",
             "Contribution": scn["vega_pnl"],
             "% of ΔP": (scn["vega_pnl"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "Sum of attributed Greeks",
             "Formula": "Δ + ½Γ·ΔS² + Θ·Δt + V·Δσ",
             "Contribution": scn["attributed"],
             "% of ΔP": (scn["attributed"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "Residual (unexplained)",
             "Formula": "BS ΔP − attributed",
             "Contribution": scn["residual"],
             "% of ΔP": (scn["residual"] / scn["bs_reprice_change"] * 100)
                        if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
            {"Component": "Total BS reprice ΔP",
             "Formula": "BS(target) − BS(base)",
             "Contribution": scn["bs_reprice_change"],
             "% of ΔP": 100.0 if abs(scn["bs_reprice_change"]) > 1e-9 else 0.0},
        ]
    )
    st.dataframe(
        pnl_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Component": st.column_config.TextColumn("Component"),
            "Formula": st.column_config.TextColumn("Formula"),
            "Contribution": st.column_config.NumberColumn("$ change", format="$%+.2f"),
            "% of ΔP": st.column_config.NumberColumn("% of ΔP", format="%+.1f%%"),
        },
    )

    # --- Sensitivity chart ---------------------------------------------------- #
    st.markdown("### Sensitivity — option price vs. underlying")
    st.caption(
        "Two curves: option price **today** (current time-to-expiry) and on the "
        "**target date** (reduced time-to-expiry). The vertical lines mark today's spot "
        "and your target underlying price."
    )

    s_lo = max(spot * 0.70, 0.01)
    s_hi = spot * 1.30
    s_lo = min(s_lo, target_price * 0.95)
    s_hi = max(s_hi, target_price * 1.05)
    s_grid = np.linspace(s_lo, s_hi, 121)

    prices_today = fc.black_scholes_price(
        s_grid, strike, T0, fc.RISK_FREE_RATE, sigma_used, opt_type_short
    )
    prices_target = fc.black_scholes_price(
        s_grid, strike, T_target, fc.RISK_FREE_RATE, sigma_used, opt_type_short
    )

    fig_w = go.Figure()
    fig_w.add_trace(
        go.Scatter(
            x=s_grid, y=prices_today, mode="lines",
            name=f"Today (T={T0 * 365.25:.0f}d)",
            line=dict(color="#42a5f5", width=2),
            hovertemplate="Underlying: $%{x:.2f}<br>Option (today): $%{y:.2f}<extra></extra>",
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=s_grid, y=prices_target, mode="lines",
            name=f"On {target_ts.strftime('%m/%d')} (T={T_target * 365.25:.0f}d)",
            line=dict(color="#ffa726", width=2, dash="dash"),
            hovertemplate=("Underlying: $%{x:.2f}<br>Option (" +
                           target_ts.strftime("%m/%d") + "): $%{y:.2f}<extra></extra>"),
        )
    )

    # Vertical markers
    fig_w.add_vline(
        x=spot, line_dash="dot", line_color="#90a4ae",
        annotation_text=f"Spot ${spot:.2f}", annotation_position="top",
    )
    fig_w.add_vline(
        x=target_price, line_dash="dot", line_color="#26a69a",
        annotation_text=f"Target ${target_price:.2f}", annotation_position="top",
    )

    # Horizontal markers for the prices at target_S
    fig_w.add_trace(
        go.Scatter(
            x=[target_price, target_price],
            y=[
                float(fc.black_scholes_price(target_price, strike, T0, fc.RISK_FREE_RATE, sigma_used, opt_type_short)),
                float(fc.black_scholes_price(target_price, strike, T_target, fc.RISK_FREE_RATE, sigma_used, opt_type_short)),
            ],
            mode="markers",
            marker=dict(size=10, color=["#42a5f5", "#ffa726"], symbol="diamond"),
            name="At target S",
            hovertemplate="$%{y:.2f}<extra></extra>",
        )
    )

    fig_w.update_layout(
        height=460,
        hovermode="x unified",
        title=f"{ticker} {option_type} ${strike:g} exp {expiration_date} — sensitivity",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig_w.update_xaxes(title_text="Underlying price (USD)")
    fig_w.update_yaxes(title_text="Option price (USD)")

    st.plotly_chart(fig_w, use_container_width=True)

    # --- Quick lookup grid ---------------------------------------------------- #
    with st.expander("Price grid: option value at various underlying prices"):
        grid_pts = np.linspace(spot * 0.85, spot * 1.15, 13)
        grid_today = fc.black_scholes_price(grid_pts, strike, T0, fc.RISK_FREE_RATE, sigma_used, opt_type_short)
        grid_target = fc.black_scholes_price(grid_pts, strike, T_target, fc.RISK_FREE_RATE, sigma_used, opt_type_short)
        grid_df = pd.DataFrame(
            {
                "Underlying": grid_pts,
                "Δ from spot": grid_pts - spot,
                "Option (today)": grid_today,
                f"Option ({target_ts.strftime('%m/%d')})": grid_target,
                "Time-decay impact": grid_target - grid_today,
            }
        )
        st.dataframe(
            grid_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Underlying": st.column_config.NumberColumn(format="$%.2f"),
                "Δ from spot": st.column_config.NumberColumn(format="$%+.2f"),
                "Option (today)": st.column_config.NumberColumn(format="$%.2f"),
                f"Option ({target_ts.strftime('%m/%d')})": st.column_config.NumberColumn(format="$%.2f"),
                "Time-decay impact": st.column_config.NumberColumn(format="$%+.2f"),
            },
        )


# -- Disclaimer ------------------------------------------------------------- #
st.markdown("---")
st.caption(
    "**Disclaimer.** These forecasts and Greeks-based estimates rely on "
    "standard Black-Scholes assumptions (lognormal returns, constant volatility, "
    "European exercise, no dividends). Real markets have jumps, volatility "
    "regimes, earnings events, and many other factors not modeled here. "
    "Do not trade based on these outputs."
)

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
import cache as fcache

st.set_page_config(
    page_title="Options Lookup",
    page_icon="📈",
    layout="wide",
)

# --------------------------------------------------------------------------- #
# Custom CSS — colorful tab styling
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
    /* Tab list container — soft rounded background */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(127, 127, 127, 0.06);
        border-radius: 14px !important;
        padding: 6px !important;
        gap: 6px !important;
    }

    /*
     * Main dashboard only (8 tabs): 4 columns × 2 rows so tabs are easy to spot.
     * Inner tab bars (e.g. Forecasts sub-tabs with 4 items) keep the default
     * single-row flex layout — selected via :has(8th tab) so we don't break them.
     */
    .stTabs [data-baseweb="tab-list"]:has([data-baseweb="tab"]:nth-child(8)) {
        display: grid !important;
        grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
        gap: 8px !important;
        width: 100% !important;
    }
    .stTabs [data-baseweb="tab-list"]:has([data-baseweb="tab"]:nth-child(8)) [data-baseweb="tab"] {
        width: 100% !important;
        min-width: 0 !important;
        flex: unset !important;
        padding: 0 10px !important;
        height: 52px !important;
        justify-content: center !important;
    }
    .stTabs [data-baseweb="tab-list"]:has([data-baseweb="tab"]:nth-child(8)) [data-baseweb="tab"] p {
        font-size: 0.86rem !important;
        text-align: center !important;
        white-space: normal !important;
        line-height: 1.25 !important;
    }

    /* Default tab styling */
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px !important;
        padding: 0 24px !important;
        height: 50px !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        border: 2px solid transparent !important;
    }
    .stTabs [data-baseweb="tab"] p {
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        margin: 0 !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    }

    /* Hide BaseWeb's default underline indicator since we use bg colors */
    .stTabs [data-baseweb="tab-highlight"] { display: none !important; }
    .stTabs [data-baseweb="tab-border"]    { display: none !important; }

    /* ---- Tab 1 — BLUE (Recent Activity / Monte Carlo sub-tab) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(1) {
        background: linear-gradient(135deg, #e3f2fd 0%, #90caf9 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(1) p { color: #0d47a1 !important; }
    .stTabs [data-baseweb="tab"]:nth-child(1)[aria-selected="true"] {
        background: linear-gradient(135deg, #1976d2 0%, #0d47a1 100%) !important;
        border-color: #0d47a1 !important;
        box-shadow: 0 4px 14px rgba(13, 71, 161, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(1)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 2 — ORANGE (5-Day Forecasts / Patterns sub-tab) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(2) {
        background: linear-gradient(135deg, #fff3e0 0%, #ffcc80 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(2) p { color: #e65100 !important; }
    .stTabs [data-baseweb="tab"]:nth-child(2)[aria-selected="true"] {
        background: linear-gradient(135deg, #f57c00 0%, #e65100 100%) !important;
        border-color: #e65100 !important;
        box-shadow: 0 4px 14px rgba(230, 81, 0, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(2)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 3 — PURPLE (What-If Scenario / ARIMA sub-tab) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(3) {
        background: linear-gradient(135deg, #f3e5f5 0%, #ce93d8 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(3) p { color: #4a148c !important; }
    .stTabs [data-baseweb="tab"]:nth-child(3)[aria-selected="true"] {
        background: linear-gradient(135deg, #8e24aa 0%, #4a148c 100%) !important;
        border-color: #4a148c !important;
        box-shadow: 0 4px 14px rgba(74, 20, 140, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(3)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 4 — GREEN (Track the Best / Random Forest sub-tab) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(4) {
        background: linear-gradient(135deg, #e8f5e9 0%, #a5d6a7 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(4) p { color: #1b5e20 !important; }
    .stTabs [data-baseweb="tab"]:nth-child(4)[aria-selected="true"] {
        background: linear-gradient(135deg, #43a047 0%, #1b5e20 100%) !important;
        border-color: #1b5e20 !important;
        box-shadow: 0 4px 14px rgba(27, 94, 32, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(4)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 5 — TEAL (Quick Summary) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(5) {
        background: linear-gradient(135deg, #e0f2f1 0%, #80cbc4 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(5) p { color: #00695c !important; }
    .stTabs [data-baseweb="tab"]:nth-child(5)[aria-selected="true"] {
        background: linear-gradient(135deg, #00897b 0%, #00695c 100%) !important;
        border-color: #00695c !important;
        box-shadow: 0 4px 14px rgba(0, 105, 92, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(5)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 6 — INDIGO (Check SMA) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(6) {
        background: linear-gradient(135deg, #e8eaf6 0%, #9fa8da 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(6) p { color: #1a237e !important; }
    .stTabs [data-baseweb="tab"]:nth-child(6)[aria-selected="true"] {
        background: linear-gradient(135deg, #3949ab 0%, #1a237e 100%) !important;
        border-color: #1a237e !important;
        box-shadow: 0 4px 14px rgba(26, 35, 126, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(6)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 7 — ROSE (Calls vs Puts) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(7) {
        background: linear-gradient(135deg, #fce4ec 0%, #f48fb1 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(7) p { color: #880e4f !important; }
    .stTabs [data-baseweb="tab"]:nth-child(7)[aria-selected="true"] {
        background: linear-gradient(135deg, #c2185b 0%, #880e4f 100%) !important;
        border-color: #880e4f !important;
        box-shadow: 0 4px 14px rgba(136, 14, 79, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(7)[aria-selected="true"] p {
        color: white !important;
    }

    /* ---- Tab 8 — WARM STONE (Cached Data) ---- */
    .stTabs [data-baseweb="tab"]:nth-child(8) {
        background: linear-gradient(135deg, #efebe9 0%, #bcaaa4 100%) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(8) p { color: #4e342e !important; }
    .stTabs [data-baseweb="tab"]:nth-child(8)[aria-selected="true"] {
        background: linear-gradient(135deg, #6d4c41 0%, #4e342e 100%) !important;
        border-color: #4e342e !important;
        box-shadow: 0 4px 14px rgba(78, 52, 46, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(8)[aria-selected="true"] p {
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

MMDD_RE = re.compile(r"^\d{2}/\d{2}$")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Caching strategy
# --------------------------------------------------------------------------- #
# Three layers of caching, designed to stay well under any rate limit:
#
#   1. Streamlit in-memory cache (`@st.cache_data`)  — fast hot path,
#      avoids redundant work within a session.
#   2. Disk-backed parquet cache (`cache.py`)         — survives restarts;
#      historical OHLCV is fetched once and only the daily delta is pulled
#      from yfinance afterwards.
#   3. Long TTLs on data that rarely changes (expirations, option chain)
#      so we don't refetch them on every interaction.
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=86400, show_spinner=False)
def get_expirations(ticker: str, live_fetch: bool = False) -> List[str]:
    """Disk-cached list of option expiration dates ('YYYY-MM-DD').

    With ``live_fetch=False`` (default) returns whatever's on disk and does
    not call yfinance.
    """
    return fcache.disk_cached_expirations(ticker, live_fetch=live_fetch)


@st.cache_data(ttl=1800, show_spinner=False)
def get_option_chain(
    ticker: str, expiration: str, live_fetch: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Disk-cached option (calls, puts) chain. ``live_fetch=False`` = no network."""
    return fcache.disk_cached_option_chain(ticker, expiration, live_fetch=live_fetch)


@st.cache_data(ttl=900, show_spinner=False)
def get_contract_history(
    contract_symbol: str, live_fetch: bool = False
) -> pd.DataFrame:
    """Disk-cached OHLCV for an option contract.

    With ``live_fetch=True``: fetches only the daily delta since the last cached
    bar (or bootstraps ~3mo on first run). With ``live_fetch=False``: pure disk
    read, no yfinance calls.
    """
    return fcache.disk_cached_history(
        contract_symbol, min_period="3mo", live_fetch=live_fetch
    )


@st.cache_data(ttl=900, show_spinner=False)
def get_underlying_history(
    ticker: str, period: str = "1y", live_fetch: bool = False
) -> pd.DataFrame:
    """Disk-cached OHLCV for the underlying stock.

    With ``live_fetch=True``: incremental delta fetch (or ~1y bootstrap on first run).
    With ``live_fetch=False``: pure disk read, no yfinance calls.
    """
    return fcache.disk_cached_history(ticker, min_period=period, live_fetch=live_fetch)


def format_cache_badge(symbol: str, live_fetch: bool) -> str | None:
    """Human-friendly 'Data updated: …' string, or None if no cache exists."""
    meta = fcache.cache_metadata(symbol)
    if meta is None:
        return None
    mode = "live" if live_fetch else "cache only"
    return (
        f"Data updated: {meta['cache_updated_at']:%Y-%m-%d %H:%M}  ·  "
        f"Last bar: {meta['last_bar_date']:%Y-%m-%d}  ·  "
        f"Mode: **{mode}**"
    )


# --------------------------------------------------------------------------- #
# Weekly-trend note (20-week MA / streak / 52-week high)
# --------------------------------------------------------------------------- #
def _ordinal(n: int) -> str:
    """Return ``'1st'``, ``'2nd'``, ``'3rd'``, ``'4th'``, ..."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def weekly_trend_note(symbol: str, df: pd.DataFrame) -> dict | None:
    """Build a 20-week MA / streak / 52-week-high trend note from daily OHLCV.

    Computes:
      - 20-week simple moving average (Friday-anchored weekly closes)
      - whether the most-recent weekly close is above/below that MA
      - the consecutive up-or-down weekly streak
      - the 52-week high (acts as the "yearly resistance" level)

    Returns a dict with raw values plus formatted ``note`` (markdown) and
    ``note_plain`` (no markdown) strings, or ``None`` if there isn't enough
    history (need at least 21 weekly bars).
    """
    if df is None or df.empty or "Close" not in df.columns:
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        return None

    # Strip TZ in-place defensively (some yfinance dumps come back tz-aware)
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    weekly = df["Close"].resample("W-FRI").last().dropna()
    if len(weekly) < 21:
        return None

    last_close = float(weekly.iloc[-1])
    ma20 = float(weekly.rolling(20).mean().iloc[-1])
    if pd.isna(ma20):
        return None
    above_ma = last_close > ma20

    diffs = weekly.diff().iloc[1:]
    streak = 0
    streak_dir: str | None = None
    for v in diffs.iloc[::-1]:
        if pd.isna(v) or v == 0:
            break
        d = "up" if v > 0 else "down"
        if streak_dir is None:
            streak_dir = d
            streak = 1
        elif d == streak_dir:
            streak += 1
        else:
            break

    one_year_ago = df.index[-1] - pd.Timedelta(weeks=52)
    yearly_window = df.loc[df.index >= one_year_ago, "Close"]
    yearly_high = (
        float(yearly_window.max())
        if not yearly_window.empty
        else float(df["Close"].max())
    )

    if streak == 0 or streak_dir is None:
        streak_str = "no clear weekly streak"
    else:
        streak_str = f"{_ordinal(streak)} {streak_dir} week in a row"

    ma20_str = f"{ma20:,.2f}"
    yh_str = f"{yearly_high:,.2f}"

    # Two parallel renderings:
    #   * ``md``    — for st.markdown. ``\$`` escapes the dollar sign so
    #                 Streamlit's MathJax doesn't pair them into a math region
    #                 (which would render ** as ∗∗ and - as −).
    #   * ``plain`` — for plain-text copy-paste, with real ``$`` and no markdown.
    if above_ma and streak_dir == "down" and streak >= 2:
        md = (
            f"**\\${symbol}** — **{streak_str}** after hitting the 52-week "
            f"high at **\\${yh_str}**. The weekly trend is still **bullish** "
            f"as long as it trades above the 20-week MA that is currently at "
            f"**\\${ma20_str}**."
        )
        plain = (
            f"${symbol} — {streak_str} after hitting the 52-week high at "
            f"${yh_str}. The weekly trend is still bullish as long as it "
            f"trades above the 20-week MA that is currently at ${ma20_str}."
        )
    elif above_ma:
        md = (
            f"**\\${symbol}** — **{streak_str}**. Weekly trend is **bullish**: "
            f"trading above the 20-week MA at **\\${ma20_str}**. "
            f"52-week high: **\\${yh_str}**."
        )
        plain = (
            f"${symbol} — {streak_str}. Weekly trend is bullish: trading "
            f"above the 20-week MA at ${ma20_str}. 52-week high: ${yh_str}."
        )
    else:
        md = (
            f"**\\${symbol}** — **{streak_str}**. The weekly trend has turned "
            f"**bearish** — currently below the 20-week MA at "
            f"**\\${ma20_str}**. 52-week high: **\\${yh_str}**."
        )
        plain = (
            f"${symbol} — {streak_str}. The weekly trend has turned bearish "
            f"— currently below the 20-week MA at ${ma20_str}. "
            f"52-week high: ${yh_str}."
        )

    return {
        "symbol": symbol,
        "last_weekly_close": last_close,
        "ma20": ma20,
        "above_ma": above_ma,
        "streak": streak,
        "streak_dir": streak_dir,
        "yearly_high": yearly_high,
        "note": md,
        "note_plain": plain,
    }


# --------------------------------------------------------------------------- #
# Cached-contract directory helpers (for the "Cached Data" tab)
# --------------------------------------------------------------------------- #
# OCC option symbol layout: ROOT + YY + MM + DD + (C|P) + STRIKE×1000 (8 digits)
# e.g. NVDA250619C00220000 = NVDA, 2025-06-19, Call, $220.00
OPTION_SYMBOL_RE = re.compile(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def parse_option_symbol(symbol: str) -> dict | None:
    """Return ticker/expiration/type/strike from an OCC option symbol, or None."""
    m = OPTION_SYMBOL_RE.match(symbol)
    if not m:
        return None
    ticker, yy, mm, dd, cp, strike_int = m.groups()
    year = 2000 + int(yy)
    return {
        "ticker": ticker,
        "expiration": f"{year}-{mm}-{dd}",
        "option_type": "Call" if cp == "C" else "Put",
        "strike": int(strike_int) / 1000.0,
        "contract_symbol": symbol,
    }


def list_cached_contracts() -> list[dict]:
    """Scan ``./.cache/`` for cached option contracts and return their metadata.

    Walks every ``*.parquet`` file in the cache directory, attempts to parse the
    stem as an OCC option symbol, and (for matches) augments with cache mtime,
    last-bar date, and row count from ``cache_metadata``.
    """
    rows: list[dict] = []
    for path in fcache.CACHE_DIR.glob("*.parquet"):
        if "__chain_" in path.name:
            continue
        parsed = parse_option_symbol(path.stem)
        if parsed is None:
            continue
        meta = fcache.cache_metadata(path.stem)
        if meta is None:
            continue
        rows.append({**parsed, **meta})
    rows.sort(key=lambda r: (r["ticker"], r["expiration"], r["option_type"], r["strike"]))
    return rows


# --------------------------------------------------------------------------- #
# Watchlist for the "Track the Best" tab
# --------------------------------------------------------------------------- #
WATCHLIST: list[tuple[str, str]] = [
    ("TSLA", "Tesla"),
    ("NVDA", "NVIDIA"),
    ("SPY", "SPY"),
    ("META", "Meta"),
    ("MSFT", "Microsoft"),
    ("AAPL", "Apple"),
    ("AMZN", "Amazon"),
    ("GOOGL", "Google"),
    ("NFLX", "Netflix"),
]


@st.cache_data(ttl=900, show_spinner=False)
def get_watchlist_movers(live_fetch: bool) -> list[dict]:
    """Compute today's % change for each ticker in WATCHLIST.

    For each ticker, loads the disk-cached OHLCV (or fetches the daily delta
    when ``live_fetch=True``), then computes the percent change between the
    last two closes. Returns a list of dicts; tickers with insufficient data
    are flagged with ``available=False``.
    """
    rows: list[dict] = []
    for symbol, name in WATCHLIST:
        try:
            # 1y of history so we have enough weekly bars for the 20-week MA
            df = fcache.disk_cached_history(
                symbol, min_period="1y", live_fetch=live_fetch
            )
        except Exception:
            df = None

        if df is None or df.empty or len(df) < 2:
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "pct": None,
                    "close": None,
                    "prev_close": None,
                    "last_bar": None,
                    "available": False,
                    "trend": None,
                }
            )
            continue

        last_close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2])
        pct = (last_close - prev_close) / prev_close * 100.0 if prev_close else 0.0
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "pct": pct,
                "close": last_close,
                "prev_close": prev_close,
                "last_bar": df.index[-1],
                "available": True,
                "trend": weekly_trend_note(symbol, df),
            }
        )
    return rows


def _trend_label(trend: dict | None) -> tuple[str, bool | None]:
    """Return (display label, above_ma) for the weekly-trend column."""
    if trend is None:
        return "—", None
    if trend["above_ma"]:
        return "▲ Bullish", True
    return "▼ Bearish", False


def _build_movers_table(rows: list[dict], direction: str) -> pd.DataFrame:
    """Build a display DataFrame for gainers or losers."""
    records: list[dict] = []
    for r in rows:
        trend = r.get("trend")
        label, _ = _trend_label(trend)
        if direction == "up":
            move = f"went up {r['pct']:.2f}%"
        else:
            move = f"went down {abs(r['pct']):.2f}%"
        weekly = (
            trend["note_plain"]
            if trend is not None
            else "Not enough history for weekly trend"
        )
        ma20 = trend["ma20"] if trend is not None else None
        records.append(
            {
                "Trend": label,
                "Stock": r["name"],
                "Today's move": move,
                "Closed at": r["close"],
                "20 week MA watchout": ma20,
                "Weekly trend": weekly,
            }
        )
    return pd.DataFrame(records)


def _style_movers_table(df: pd.DataFrame, direction: str):
    """Color the Trend column (green/red) and the move/close columns."""

    def _hl_trend(col: pd.Series) -> list[str]:
        styles = []
        for v in col:
            if "Bearish" in str(v):
                styles.append("color: #c62828; font-weight: 700")
            elif "Bullish" in str(v):
                styles.append("color: #2e7d32; font-weight: 700")
            else:
                styles.append("")
        return styles

    move_color = "#2e7d32" if direction == "up" else "#c62828"

    styled = (
        df.style
        .apply(_hl_trend, subset=["Trend"])
        .format(
            {
                "Closed at": "${:,.2f}",
                "20 week MA watchout": "${:,.2f}",
            },
            na_rep="—",
        )
    )
    styled = styled.set_properties(
        subset=["Today's move"],
        **{"color": move_color, "font-weight": "600"},
    )
    return styled


def _sma_vs_label(close: float, sma: float) -> tuple[str, bool]:
    """Return ``'Above (Bullish)'`` / ``'Below (Bearish)'`` and whether above."""
    above = close > sma
    if above:
        return "Above (Bullish)", True
    return "Below (Bearish)", False


def _overall_sma_trend(above_50: bool, above_200: bool) -> str:
    """Plain-English trend label from 50-day and 200-day SMA positions."""
    if above_50 and above_200:
        return "Long-term Uptrend"
    if not above_50 and not above_200:
        return "Downtrend"
    if above_50 and not above_200:
        return "Mixed"
    return "Pullback"


@st.cache_data(ttl=900, show_spinner=False)
def get_sma_summary_table(live_fetch: bool) -> pd.DataFrame:
    """50-day / 200-day SMA quick summary for every ticker in WATCHLIST."""
    records: list[dict] = []
    for symbol, name in WATCHLIST:
        try:
            df = fcache.disk_cached_history(
                symbol, min_period="1y", live_fetch=live_fetch
            )
        except Exception:
            df = None

        if df is None or df.empty or len(df) < 200:
            records.append(
                {
                    "Stock": symbol,
                    "Name": name,
                    "Price (approx.)": None,
                    "50-day SMA price": None,
                    "vs 50-day SMA": "—",
                    "200-day SMA price": None,
                    "vs 200-day SMA": "—",
                    "Overall Trend": "Not enough history (need ~200 days)",
                    "_above_50": None,
                    "_above_200": None,
                }
            )
            continue

        if df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)

        close = float(df["Close"].iloc[-1])
        sma50 = float(df["Close"].rolling(50).mean().iloc[-1])
        sma200 = float(df["Close"].rolling(200).mean().iloc[-1])
        vs50, above_50 = _sma_vs_label(close, sma50)
        vs200, above_200 = _sma_vs_label(close, sma200)

        records.append(
            {
                "Stock": symbol,
                "Name": name,
                "Price (approx.)": close,
                "50-day SMA price": sma50,
                "vs 50-day SMA": vs50,
                "200-day SMA price": sma200,
                "vs 200-day SMA": vs200,
                "Overall Trend": _overall_sma_trend(above_50, above_200),
                "_above_50": above_50,
                "_above_200": above_200,
            }
        )
    return pd.DataFrame(records)


def _style_sma_table(df: pd.DataFrame):
    """Green/red styling for Quick Summary and Check SMA tables."""

    def _hl_sma(col: pd.Series) -> list[str]:
        styles = []
        for v in col:
            if "Bullish" in str(v):
                styles.append("color: #2e7d32; font-weight: 700")
            elif "Bearish" in str(v):
                styles.append("color: #c62828; font-weight: 700")
            else:
                styles.append("")
        return styles

    display = df.drop(columns=["Name", "_above_50", "_above_200"], errors="ignore")
    return (
        display.style
        .apply(_hl_sma, subset=["vs 50-day SMA", "vs 200-day SMA"])
        .format(
            {
                "Price (approx.)": "${:,.0f}",
                "50-day SMA price": "${:,.2f}",
                "200-day SMA price": "${:,.2f}",
                "20 week MA watchout": "${:,.2f}",
            },
            na_rep="—",
        )
    )


def _parse_ticker_list(raw: str) -> list[str]:
    """Split comma/space-separated tickers into a deduped upper-case list."""
    parts = re.split(r"[\s,;]+", raw.strip())
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        t = p.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_sma_check_row(symbol: str, df: pd.DataFrame | None) -> dict:
    """One SMA check row for *symbol* using cached or live OHLCV."""
    symbol = symbol.strip().upper()
    empty = {
        "Stock": symbol,
        "Price (approx.)": None,
        "50-day SMA price": None,
        "vs 50-day SMA": "—",
        "200-day SMA price": None,
        "vs 200-day SMA": "—",
        "20 week MA watchout": None,
        "Weekly trend": "—",
        "Overall Trend": "No data on disk — enable live fetch",
        "_above_50": None,
        "_above_200": None,
    }
    if df is None or df.empty:
        return empty

    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    close = float(df["Close"].iloc[-1])
    trend = weekly_trend_note(symbol, df)

    row: dict = {
        "Stock": symbol,
        "Price (approx.)": close,
        "50-day SMA price": None,
        "vs 50-day SMA": "—",
        "200-day SMA price": None,
        "vs 200-day SMA": "—",
        "20 week MA watchout": trend["ma20"] if trend else None,
        "Weekly trend": (
            trend["note_plain"] if trend else "Not enough history for weekly trend"
        ),
        "Overall Trend": "—",
        "_above_50": None,
        "_above_200": None,
    }

    above_50: bool | None = None
    above_200: bool | None = None

    if len(df) >= 50:
        sma50 = float(df["Close"].rolling(50).mean().iloc[-1])
        vs50, above_50 = _sma_vs_label(close, sma50)
        row["50-day SMA price"] = sma50
        row["vs 50-day SMA"] = vs50
        row["_above_50"] = above_50
    else:
        row["vs 50-day SMA"] = "Need ~50 days of history"

    if len(df) >= 200:
        sma200 = float(df["Close"].rolling(200).mean().iloc[-1])
        vs200, above_200 = _sma_vs_label(close, sma200)
        row["200-day SMA price"] = sma200
        row["vs 200-day SMA"] = vs200
        row["_above_200"] = above_200
    else:
        row["vs 200-day SMA"] = "Need ~200 days of history"

    if above_50 is not None and above_200 is not None:
        row["Overall Trend"] = _overall_sma_trend(above_50, above_200)
    elif above_50 is not None:
        row["Overall Trend"] = "Partial — need ~200 days for full SMA trend"
    elif len(df) < 50:
        row["Overall Trend"] = "Not enough history"

    return row


@st.cache_data(ttl=900, show_spinner=False)
def lookup_sma_check(tickers: tuple[str, ...], live_fetch: bool) -> pd.DataFrame:
    """Fetch SMA + weekly trend rows for arbitrary tickers."""
    rows: list[dict] = []
    for symbol in tickers:
        try:
            df = fcache.disk_cached_history(
                symbol, min_period="1y", live_fetch=live_fetch
            )
        except Exception:
            df = None
        rows.append(build_sma_check_row(symbol, df))
    return pd.DataFrame(rows)


_CHECK_SMA_METRICS: list[str] = [
    "Price (approx.)",
    "50-day SMA price",
    "vs 50-day SMA",
    "200-day SMA price",
    "vs 200-day SMA",
    "20 week MA watchout",
    "Overall Trend",
    "Weekly trend",
]

# Shown in the vertical table — Weekly trend is rendered separately so it
# can word-wrap cleanly (dataframe cells do not wrap long text well).
_CHECK_SMA_TABLE_METRICS: list[str] = [
    m for m in _CHECK_SMA_METRICS if m != "Weekly trend"
]


def _format_check_sma_cell(field: str, val) -> str:
    """Format one cell for the vertical Check SMA table."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if field == "Price (approx.)":
        return f"${float(val):,.0f}"
    if field in ("50-day SMA price", "200-day SMA price", "20 week MA watchout"):
        return f"${float(val):,.2f}"
    return str(val)


def check_sma_vertical_table(
    check_df: pd.DataFrame,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """Transpose Check SMA results — metrics as rows, each ticker as a column."""
    if check_df.empty:
        return pd.DataFrame(columns=["Metric"])

    fields = metrics if metrics is not None else _CHECK_SMA_TABLE_METRICS
    records: list[dict] = []
    for field in fields:
        row: dict = {"Metric": field}
        for _, r in check_df.iterrows():
            row[r["Stock"]] = _format_check_sma_cell(field, r.get(field))
        records.append(row)
    return pd.DataFrame(records)


def _style_check_sma_vertical(df: pd.DataFrame):
    """Green/red on vs-SMA rows in the vertical Check SMA layout."""

    def _hl_row(row: pd.Series) -> list[str]:
        if row["Metric"] not in ("vs 50-day SMA", "vs 200-day SMA"):
            return [""] * len(row)
        styles = ["font-weight: 600"]
        for col in df.columns[1:]:
            text = str(row[col])
            if "Bullish" in text:
                styles.append("color: #2e7d32; font-weight: 700")
            elif "Bearish" in text:
                styles.append("color: #c62828; font-weight: 700")
            else:
                styles.append("")
        return styles

    styled = df.style.apply(_hl_row, axis=1)
    styled = styled.set_properties(
        subset=["Metric"],
        **{"font-weight": "600", "background-color": "rgba(127,127,127,0.06)"},
    )
    return styled


def _sum_option_column(df: pd.DataFrame | None, col: str) -> int:
    """Safely sum a numeric column on an option chain DataFrame."""
    if df is None or df.empty or col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def _dominance_verdict(
    winner: str, call_val: int, put_val: int, metric: str
) -> str:
    """Plain-English one-liner for call vs put dominance."""
    total = call_val + put_val
    if total == 0:
        return f"No {metric.lower()} reported for calls or puts on this chain."
    if winner == "Tied":
        return f"Calls and puts are **even** on {metric.lower()} — no clear lean."
    loser_val = put_val if winner == "Calls" else call_val
    winner_val = call_val if winner == "Calls" else put_val
    margin_pct = (winner_val - loser_val) / total * 100.0
    bias = "bullish" if winner == "Calls" else "bearish"
    return (
        f"**{winner} dominate** on {metric.lower()}: "
        f"{winner_val:,} vs {loser_val:,} "
        f"({margin_pct:.1f}% of total). Leans **{bias}** for this expiration."
    )


def analyze_put_call_balance(
    calls: pd.DataFrame, puts: pd.DataFrame
) -> dict:
    """Aggregate volume & open interest to see whether calls or puts dominate."""
    call_vol = _sum_option_column(calls, "volume")
    put_vol = _sum_option_column(puts, "volume")
    call_oi = _sum_option_column(calls, "openInterest")
    put_oi = _sum_option_column(puts, "openInterest")
    call_strikes = len(calls) if calls is not None and not calls.empty else 0
    put_strikes = len(puts) if puts is not None and not puts.empty else 0

    if call_vol > put_vol:
        vol_winner = "Calls"
    elif put_vol > call_vol:
        vol_winner = "Puts"
    else:
        vol_winner = "Tied"

    if call_oi > put_oi:
        oi_winner = "Calls"
    elif put_oi > call_oi:
        oi_winner = "Puts"
    else:
        oi_winner = "Tied"

    total_vol = call_vol + put_vol
    total_oi = call_oi + put_oi
    pc_ratio_vol = put_vol / call_vol if call_vol > 0 else None
    pc_ratio_oi = put_oi / call_oi if call_oi > 0 else None

    return {
        "call_volume": call_vol,
        "put_volume": put_vol,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "call_strikes": call_strikes,
        "put_strikes": put_strikes,
        "volume_winner": vol_winner,
        "oi_winner": oi_winner,
        "call_volume_pct": call_vol / total_vol * 100.0 if total_vol else 0.0,
        "put_volume_pct": put_vol / total_vol * 100.0 if total_vol else 0.0,
        "call_oi_pct": call_oi / total_oi * 100.0 if total_oi else 0.0,
        "put_oi_pct": put_oi / total_oi * 100.0 if total_oi else 0.0,
        "put_call_ratio_volume": pc_ratio_vol,
        "put_call_ratio_oi": pc_ratio_oi,
        "volume_verdict": _dominance_verdict(vol_winner, call_vol, put_vol, "Volume"),
        "oi_verdict": _dominance_verdict(oi_winner, call_oi, put_oi, "Open interest"),
    }


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_put_call_analysis(
    ticker: str, expiration: str, live_fetch: bool
) -> dict | None:
    """Load option chain and return put/call dominance stats."""
    calls, puts = get_option_chain(ticker, expiration, live_fetch=live_fetch)
    if (calls is None or calls.empty) and (puts is None or puts.empty):
        return None
    return analyze_put_call_balance(calls, puts)


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
# Sidebar: data source toggle (cache-only vs. live)
# --------------------------------------------------------------------------- #
st.sidebar.markdown("### Data source")
live_fetch = st.sidebar.checkbox(
    "Fetch live data from Yahoo Finance",
    value=False,
    key="live_fetch",
    help=(
        "When **unchecked** (default), the app uses ONLY locally-cached data — "
        "no calls to Yahoo Finance. Safest for staying under rate limits.\n\n"
        "When **checked**, the app refreshes the cache: fetches just the daily "
        "delta for OHLCV history, and re-pulls expirations + option chain."
    ),
)
if live_fetch:
    st.sidebar.caption(
        ":green[**Live mode**] — Yahoo Finance will be called and the disk "
        "cache will be updated."
    )
else:
    st.sidebar.caption(
        ":blue[**Cache-only mode**] — using whatever is already on disk. "
        "No network calls."
    )

# Streamlit's @st.cache_data memoizes per-argument. If a fetch was attempted
# in cache-only mode BEFORE disk had any data for that ticker, an empty
# result gets memoized under the live_fetch=False key. Later, after the user
# enables live mode and disk gets populated, switching back to cache-only
# would otherwise still return that stale-empty memoized value.
# So whenever live_fetch toggles, drop the four in-memory caches — the disk
# is the source of truth and reads are <50ms.
_prev_live_fetch = st.session_state.get("_prev_live_fetch")
if _prev_live_fetch is not None and _prev_live_fetch != live_fetch:
    get_expirations.clear()
    get_option_chain.clear()
    get_contract_history.clear()
    get_underlying_history.clear()
    get_watchlist_movers.clear()
    get_sma_summary_table.clear()
    lookup_sma_check.clear()
    fetch_put_call_analysis.clear()
st.session_state["_prev_live_fetch"] = live_fetch


# --------------------------------------------------------------------------- #
# Sidebar: cache management
# --------------------------------------------------------------------------- #
with st.sidebar.expander("Cache settings", expanded=False):
    summary = fcache.cache_summary()
    st.caption(
        f"**Disk cache:** `{summary['directory']}`\n\n"
        f"**Files:** {summary['num_files']}  ·  "
        f"**Size:** {summary['total_kb']} KB"
    )
    st.caption(
        "OHLCV data is cached on disk and only the **daily delta** is fetched "
        "from Yahoo Finance when *Fetch live data* is checked above."
    )

    # Show the most recently updated OHLCV caches.
    # Option-chain snapshots ("__chain_") and expirations ("__expirations") are
    # excluded — they aren't time-series and don't have a meaningful "last bar".
    parquet_paths = sorted(
        (
            p
            for p in fcache.CACHE_DIR.glob("*.parquet")
            if "__chain_" not in p.name
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if parquet_paths:
        rows = []
        for p in parquet_paths[:8]:
            symbol = p.stem
            meta = fcache.cache_metadata(symbol)
            if meta is None:
                continue
            rows.append(
                f"- `{symbol}` · "
                f"updated {meta['cache_updated_at']:%Y-%m-%d %H:%M} · "
                f"last bar {meta['last_bar_date']:%Y-%m-%d}"
            )
        if rows:
            st.caption("**Recently updated:**")
            st.markdown("\n".join(rows))

    confirm_wipe = st.checkbox(
        "Yes, wipe everything",
        value=False,
        key="confirm_cache_wipe",
        help=(
            "Safety belt — you must check this before the **Clear all cached "
            "data** button will actually delete files. This is irreversible "
            "and affects every cached symbol (OHLCV, option chains, expirations)."
        ),
    )
    if st.button(
        "Clear all cached data",
        use_container_width=True,
        disabled=not confirm_wipe,
    ):
        n = fcache.clear_cache(confirm=True)
        st.cache_data.clear()
        st.success(f"Cleared {n} cached file(s) and reset in-memory cache.")
        st.session_state["confirm_cache_wipe"] = False
        st.rerun()


# --------------------------------------------------------------------------- #
# Main panel
# --------------------------------------------------------------------------- #
st.title("Stock Options Dashboard")
st.caption(
    "Enter a ticker, option type, expiration (MM/DD) and strike on the left, "
    "then click **Fetch Data**. Eight tabs in two rows (4 + 4): recent activity, 5-day "
    "forecasts, a Greeks-based what-if calculator, today's watchlist movers, "
    "a 50/200-day SMA quick summary, a custom SMA checker, calls-vs-puts "
    "dominance, and cached contracts. "
    "Data is sourced from Yahoo Finance via yfinance."
)

# Top-level tabs are defined up-front so the Track-the-Best (watchlist) tab is
# always rendered, even before the user submits the contract form.
# Layout (CSS grid 4×2): row 1 = contract tools, row 2 = watchlist & scanners.
st.caption(
    "**Row 1 — Contract:** Recent Activity · 5-Day Forecasts · What-If · Track the Best  \n"
    "**Row 2 — Scanners:** Quick Summary · Check SMA · Calls vs Puts · Cached Data"
)
tab_recent, tab_forecast, tab_whatif, tab_movers, tab_summary, tab_check_sma, tab_pcr, tab_cached = st.tabs([
    "Recent Activity",
    "5-Day Forecasts",
    "What-If Scenario",
    "Track the Best",
    "Quick Summary",
    "Check SMA",
    "Calls vs Puts",
    "Cached Data",
])


# --------------------------------------------------------------------------- #
# Track-the-Best tab — daily movers from a fixed watchlist
# --------------------------------------------------------------------------- #
with tab_movers:
    st.markdown("### Daily Movers — Watchlist")
    st.caption(
        "A quick read on the day's biggest moves across a fixed watchlist. "
        "Each row shows today's move, the closing price, the **20-week MA "
        "watchout** level, and the weekly trend "
        "(▲ Bullish in green = above 20-week MA, ▼ Bearish in red = below)."
    )

    movers_live = st.checkbox(
        "Fetch live data for watchlist",
        value=False,
        key="movers_live_fetch",
        help=(
            "When **unchecked** (default), uses ONLY locally-cached data on "
            "disk — no calls to Yahoo Finance. Tick this and click **Refresh** "
            "to pull the latest closes for all watchlist tickers."
        ),
    )

    # Same staleness guard as the sidebar's live_fetch: toggling this flag
    # invalidates the in-memory watchlist cache so refreshed disk data is
    # picked up the next read.
    _prev_movers_live = st.session_state.get("_prev_movers_live")
    if _prev_movers_live is not None and _prev_movers_live != movers_live:
        get_watchlist_movers.clear()
    st.session_state["_prev_movers_live"] = movers_live

    mc1, mc2 = st.columns([1, 4])
    with mc1:
        if st.button("Refresh now", use_container_width=True, key="movers_refresh"):
            get_watchlist_movers.clear()
            st.rerun()
    with mc2:
        if movers_live:
            st.caption(
                ":green[**Live mode**] — Yahoo Finance will be called and "
                "the disk cache will be refreshed."
            )
        else:
            st.caption(
                ":blue[**Cache-only mode**] — using whatever is already on disk."
            )

    with st.spinner("Loading watchlist…"):
        movers = get_watchlist_movers(live_fetch=movers_live)

    available = [r for r in movers if r["available"]]
    unavailable = [r for r in movers if not r["available"]]
    gainers = sorted(
        (r for r in available if r["pct"] is not None and r["pct"] > 0),
        key=lambda r: r["pct"], reverse=True,
    )
    losers = sorted(
        (r for r in available if r["pct"] is not None and r["pct"] < 0),
        key=lambda r: r["pct"],
    )
    flat = [r for r in available if r["pct"] == 0]

    _movers_col_config = {
        "Trend": st.column_config.TextColumn(
            "Trend",
            help="▲ Bullish = above 20-week MA. ▼ Bearish = below.",
            width="small",
        ),
        "Stock": st.column_config.TextColumn("Stock", width="small"),
        "Today's move": st.column_config.TextColumn(
            "Today's move", width="medium"
        ),
        "Closed at": st.column_config.NumberColumn("Closed at", format="$%.2f"),
        "20 week MA watchout": st.column_config.NumberColumn(
            "20 week MA watchout",
            format="$%.2f",
            help=(
                "The 20-week moving average — the key level to "
                "watch. Above = bullish weekly trend, below = bearish."
            ),
        ),
        "Weekly trend": st.column_config.TextColumn(
            "Weekly trend",
            help="Streak, 52-week high, and trend commentary.",
            width="large",
        ),
    }

    # Losers first (top), gainers second (bottom) — full width, stacked vertically.
    st.markdown(f"#### :red[📉 What went down today] ({len(losers)})")
    if not losers:
        st.caption(
            "Nothing in the red today — or no cached data yet. "
            "Tick **Fetch live data for watchlist** above and click **Refresh**."
        )
    else:
        down_df = _build_movers_table(losers, direction="down")
        st.dataframe(
            _style_movers_table(down_df, direction="down"),
            use_container_width=True,
            hide_index=True,
            column_config=_movers_col_config,
        )

    st.markdown(f"#### :green[📈 What went up today] ({len(gainers)})")
    if not gainers:
        st.caption(
            "Nothing in the green today — or no cached data yet. "
            "Tick **Fetch live data for watchlist** above and click **Refresh**."
        )
    else:
        up_df = _build_movers_table(gainers, direction="up")
        st.dataframe(
            _style_movers_table(up_df, direction="up"),
            use_container_width=True,
            hide_index=True,
            column_config=_movers_col_config,
        )

    if flat:
        st.caption(
            "**Flat (0.00%):** "
            + ", ".join(r["name"] for r in flat)
        )

    if unavailable:
        st.warning(
            "No cached data for: "
            + ", ".join(f"`{r['symbol']}`" for r in unavailable)
            + ". Tick **Fetch live data for watchlist** above and click "
            "**Refresh** to download initial history for them."
        )

    # Plain-text version with a one-click copy button — easy to paste into
    # Slack, email, Notes, etc. without any color codes or markdown bleeding in.
    if gainers or losers:
        plain_lines: list[str] = []
        for r in gainers:
            label, _ = _trend_label(r.get("trend"))
            ma_part = ""
            if r.get("trend") and r["trend"].get("ma20") is not None:
                ma_part = f" | 20 week MA watchout: ${r['trend']['ma20']:,.2f}"
            plain_lines.append(
                f"{label} | {r['name']} went up today by {r['pct']:.2f}% "
                f"and closed at ${r['close']:,.2f}{ma_part}"
            )
            if r.get("trend"):
                plain_lines.append(r["trend"]["note_plain"])
            plain_lines.append("")
        for r in losers:
            label, _ = _trend_label(r.get("trend"))
            ma_part = ""
            if r.get("trend") and r["trend"].get("ma20") is not None:
                ma_part = f" | 20 week MA watchout: ${r['trend']['ma20']:,.2f}"
            plain_lines.append(
                f"{label} | {r['name']} went down today by {abs(r['pct']):.2f}% "
                f"and closed at ${r['close']:,.2f}{ma_part}"
            )
            if r.get("trend"):
                plain_lines.append(r["trend"]["note_plain"])
            plain_lines.append("")
        with st.expander("📋 Copy these lines (plain text)", expanded=False):
            st.caption(
                "Click the copy icon in the top-right of the box below — "
                "the text will paste cleanly into Slack, email, or any app."
            )
            st.code("\n".join(plain_lines).rstrip(), language="text")


# --------------------------------------------------------------------------- #
# Quick Summary tab — 50-day & 200-day SMA table
# --------------------------------------------------------------------------- #
with tab_summary:
    st.markdown("### Quick Summary Table")
    st.caption(
        "Where each watchlist stock sits vs its **50-day** and **200-day** "
        "simple moving averages (SMA), including the actual SMA price levels. "
        "**Above (Bullish)** in green = price is above that SMA. "
        "**Below (Bearish)** in red = price is below."
    )

    summary_live = st.checkbox(
        "Fetch live data for summary",
        value=False,
        key="summary_live_fetch",
        help=(
            "When **unchecked** (default), uses ONLY locally-cached data on "
            "disk. Tick this and click **Refresh** to pull the latest closes."
        ),
    )

    _prev_summary_live = st.session_state.get("_prev_summary_live")
    if _prev_summary_live is not None and _prev_summary_live != summary_live:
        get_sma_summary_table.clear()
    st.session_state["_prev_summary_live"] = summary_live

    sc1, sc2 = st.columns([1, 4])
    with sc1:
        if st.button("Refresh now", use_container_width=True, key="summary_refresh"):
            get_sma_summary_table.clear()
            st.rerun()
    with sc2:
        if summary_live:
            st.caption(
                ":green[**Live mode**] — Yahoo Finance will be called and "
                "the disk cache will be refreshed."
            )
        else:
            st.caption(
                ":blue[**Cache-only mode**] — using whatever is already on disk."
            )

    with st.spinner("Building SMA summary…"):
        sma_df = get_sma_summary_table(live_fetch=summary_live)

    if sma_df.empty:
        st.info("No watchlist data available.")
    else:
        st.dataframe(
            _style_sma_table(sma_df),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Stock": st.column_config.TextColumn(
                    "Stock",
                    help="Ticker symbol.",
                    width="small",
                ),
                "Price (approx.)": st.column_config.NumberColumn(
                    "Price (approx.)",
                    format="$%.0f",
                    help="Latest closing price (rounded to nearest dollar).",
                ),
                "50-day SMA price": st.column_config.NumberColumn(
                    "50-day SMA price",
                    format="$%.2f",
                    help="Current 50-day simple moving average level.",
                ),
                "vs 50-day SMA": st.column_config.TextColumn(
                    "vs 50-day SMA",
                    help="Medium-term trend — above = bullish, below = bearish.",
                ),
                "200-day SMA price": st.column_config.NumberColumn(
                    "200-day SMA price",
                    format="$%.2f",
                    help="Current 200-day simple moving average level.",
                ),
                "vs 200-day SMA": st.column_config.TextColumn(
                    "vs 200-day SMA",
                    help="Long-term trend — above = bullish, below = bearish.",
                ),
                "Overall Trend": st.column_config.TextColumn(
                    "Overall Trend",
                    help=(
                        "Long-term Uptrend = above both. Downtrend = below both. "
                        "Mixed = above 50-day but below 200-day. "
                        "Pullback = below 50-day but still above 200-day."
                    ),
                ),
            },
        )

        # Plain-text copy
        copy_lines: list[str] = []
        for _, row in sma_df.iterrows():
            price = row["Price (approx.)"]
            price_str = f"${price:,.0f}" if pd.notna(price) else "—"
            sma50_str = (
                f"${row['50-day SMA price']:,.2f}"
                if pd.notna(row.get("50-day SMA price"))
                else "—"
            )
            sma200_str = (
                f"${row['200-day SMA price']:,.2f}"
                if pd.notna(row.get("200-day SMA price"))
                else "—"
            )
            copy_lines.append(
                f"{row['Stock']} | Price: {price_str} | "
                f"50-day SMA: {sma50_str} ({row['vs 50-day SMA']}) | "
                f"200-day SMA: {sma200_str} ({row['vs 200-day SMA']}) | "
                f"Overall: {row['Overall Trend']}"
            )
        with st.expander("📋 Copy summary (plain text)", expanded=False):
            st.code("\n".join(copy_lines), language="text")


# --------------------------------------------------------------------------- #
# Check SMA tab — look up any ticker(s)
# --------------------------------------------------------------------------- #
with tab_check_sma:
    st.markdown("### Check SMA (Simple Moving Average)")
    st.caption(
        "Look up **any** stock ticker — one or several at once. "
        "Uses disk cache by default; tick **Fetch live data** to refresh "
        "from Yahoo Finance."
    )

    with st.form("check_sma_form"):
        check_sma_input = st.text_input(
            "Stock ticker(s)",
            value=st.session_state.get("sma_check_input", "NVDA"),
            placeholder="NVDA  or  NVDA, MSFT, TSLA",
            help="One ticker, or several separated by commas or spaces.",
        )
        check_sma_live = st.checkbox(
            "Fetch live data",
            value=st.session_state.get("sma_check_live", False),
            help=(
                "When unchecked, reads ONLY from the local disk cache. "
                "When checked, refreshes from Yahoo Finance and updates the cache."
            ),
        )
        check_sma_submitted = st.form_submit_button(
            "Look up", use_container_width=True
        )

    if check_sma_submitted:
        parsed = _parse_ticker_list(check_sma_input)
        if not parsed:
            st.error("Enter at least one valid ticker symbol.")
        else:
            st.session_state["sma_check_input"] = check_sma_input
            st.session_state["sma_check_tickers"] = tuple(parsed)
            st.session_state["sma_check_live"] = check_sma_live
            lookup_sma_check.clear()

    _prev_check_live = st.session_state.get("_prev_check_sma_live")
    if _prev_check_live is not None and _prev_check_live != st.session_state.get(
        "sma_check_live", False
    ):
        lookup_sma_check.clear()
    st.session_state["_prev_check_sma_live"] = st.session_state.get(
        "sma_check_live", False
    )

    if "sma_check_tickers" not in st.session_state:
        st.info(
            "Enter a ticker above and click **Look up**. "
            "Example: `NVDA` or `NVDA, MSFT, AAPL`."
        )
    else:
        tickers = st.session_state["sma_check_tickers"]
        check_live = st.session_state.get("sma_check_live", False)

        if check_live:
            st.caption(
                ":green[**Live mode**] — Yahoo Finance will be called for "
                f"{len(tickers)} ticker(s)."
            )
        else:
            st.caption(
                ":blue[**Cache-only mode**] — using whatever is already on disk."
            )

        with st.spinner(f"Looking up {len(tickers)} ticker(s)…"):
            check_df = lookup_sma_check(tickers, live_fetch=check_live)

        vertical_df = check_sma_vertical_table(check_df)
        st.caption(
            "Metrics run **down** the left — each ticker is its own **column**. "
            "Scroll sideways if you looked up several tickers at once."
        )
        st.dataframe(
            _style_check_sma_vertical(vertical_df),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Metric": st.column_config.TextColumn(
                    "Metric",
                    help="Field name — read down this column.",
                    width="medium",
                ),
                **{
                    sym: st.column_config.TextColumn(
                        sym,
                        help=f"SMA summary for {sym}.",
                        width="large",
                    )
                    for sym in tickers
                },
            },
        )

        st.markdown("#### Weekly trend")
        st.caption("Word-wrapped for easier reading — one block per ticker.")
        for _, row in check_df.iterrows():
            trend_text = row.get("Weekly trend") or "—"
            above_ma = row.get("_above_50")
            with st.container(border=True):
                st.markdown(f"**{row['Stock']}**")
                if above_ma is True:
                    st.success(trend_text)
                elif above_ma is False and pd.notna(row.get("Price (approx.)")):
                    st.error(trend_text)
                else:
                    st.info(trend_text)

        no_data = check_df[
            check_df["Price (approx.)"].isna()
        ]["Stock"].tolist()
        if no_data and not check_live:
            st.warning(
                "No cached data for: "
                + ", ".join(f"`{s}`" for s in no_data)
                + ". Tick **Fetch live data** and click **Look up** again."
            )

        copy_check: list[str] = []
        for _, row in check_df.iterrows():
            price = row["Price (approx.)"]
            if pd.isna(price):
                copy_check.append(f"{row['Stock']} | {row['Overall Trend']}")
                continue
            sma50 = row.get("50-day SMA price")
            sma200 = row.get("200-day SMA price")
            ma20 = row.get("20 week MA watchout")
            sma50_str = f"${sma50:,.2f}" if pd.notna(sma50) else "—"
            sma200_str = f"${sma200:,.2f}" if pd.notna(sma200) else "—"
            ma20_str = f"${ma20:,.2f}" if pd.notna(ma20) else "—"
            copy_check.append(
                f"{row['Stock']} | Price: ${price:,.0f} | "
                f"50-day SMA: {sma50_str} ({row['vs 50-day SMA']}) | "
                f"200-day SMA: {sma200_str} ({row['vs 200-day SMA']}) | "
                f"20 week MA: {ma20_str} | "
                f"Weekly: {row['Weekly trend']} | "
                f"Overall: {row['Overall Trend']}"
            )
        with st.expander("📋 Copy results (plain text)", expanded=False):
            st.code("\n".join(copy_check), language="text")


# --------------------------------------------------------------------------- #
# Calls vs Puts tab — put/call dominance for any ticker + expiration
# --------------------------------------------------------------------------- #
with tab_pcr:
    st.markdown("### Calls vs Puts — Who Dominates?")
    st.caption(
        "Compare how many **calls** vs **puts** traded (volume) and how many "
        "are still open (open interest) for a chosen expiration. "
        "Defaults to **SPY** — change the ticker if you like."
    )

    with st.expander("How to read this (30-second guide)", expanded=False):
        st.markdown(textwrap.dedent("""
            - **Volume** = contracts traded in the latest session (today's activity).
            - **Open interest** = total contracts still open (longer-term positioning).
            - **More calls** → traders leaning **bullish** (betting the stock goes up).
            - **More puts** → traders leaning **bearish** (betting it goes down).
            - **Put/Call ratio** = puts ÷ calls. Above **1.0** = puts dominate.
              Below **1.0** = calls dominate.

            This is a **sentiment snapshot**, not a buy/sell signal on its own —
            use it alongside price, SMA trends, and your own plan.
        """).strip())

    with st.form("pcr_form"):
        pcr_ticker = st.text_input(
            "Ticker",
            value=st.session_state.get("pcr_ticker", "SPY"),
            help="e.g. SPY, QQQ, AAPL",
        )
        pcr_exp_input = st.text_input(
            "Expiration (MM/DD)",
            value=st.session_state.get("pcr_exp_input", ""),
            placeholder="e.g. 06/20",
            help="Option expiration date in month/day format.",
        )
        pcr_live = st.checkbox(
            "Fetch live data",
            value=st.session_state.get("pcr_live", False),
            help="Unchecked = disk cache only. Checked = refresh chain from Yahoo Finance.",
        )
        pcr_submitted = st.form_submit_button("Analyze", use_container_width=True)

    if pcr_submitted:
        pcr_t = pcr_ticker.strip().upper()
        if not pcr_t:
            st.error("Enter a ticker symbol.")
        elif not MMDD_RE.match(pcr_exp_input.strip()):
            st.error("Expiration must be in MM/DD format (e.g. `06/20`).")
        else:
            st.session_state["pcr_ticker"] = pcr_t
            st.session_state["pcr_exp_input"] = pcr_exp_input.strip()
            st.session_state["pcr_live"] = pcr_live
            st.session_state["pcr_ready"] = True
            fetch_put_call_analysis.clear()

    _prev_pcr_live = st.session_state.get("_prev_pcr_live")
    if _prev_pcr_live is not None and _prev_pcr_live != st.session_state.get(
        "pcr_live", False
    ):
        fetch_put_call_analysis.clear()
    st.session_state["_prev_pcr_live"] = st.session_state.get("pcr_live", False)

    if not st.session_state.get("pcr_ready"):
        st.info(
            "Enter a ticker (default **SPY**), an expiration like **06/20**, "
            "and click **Analyze**."
        )
    else:
        pcr_t = st.session_state["pcr_ticker"]
        pcr_exp_raw = st.session_state["pcr_exp_input"]
        pcr_mm, pcr_dd = (int(x) for x in pcr_exp_raw.split("/"))
        pcr_live_flag = st.session_state.get("pcr_live", False)

        if pcr_live_flag:
            st.caption(":green[**Live mode**] — refreshing option chain from Yahoo Finance.")
        else:
            st.caption(":blue[**Cache-only mode**] — using cached chain if available.")

        with st.spinner(f"Loading expirations for {pcr_t}…"):
            try:
                pcr_exps = get_expirations(pcr_t, live_fetch=pcr_live_flag)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not fetch expirations for `{pcr_t}`: {exc}")
                pcr_exps = []

        if not pcr_exps:
            if not pcr_live_flag:
                st.warning(
                    f"No cached expirations for `{pcr_t}`. "
                    "Tick **Fetch live data** and click **Analyze** again."
                )
            else:
                st.error(f"`{pcr_t}` has no listed options on Yahoo Finance.")
        else:
            try:
                pcr_exp_date = resolve_expiration(pcr_mm, pcr_dd, pcr_exps)
            except ValueError:
                upcoming = nearest_expirations(pcr_exps)
                st.error(
                    f"No expiration matches **{pcr_exp_raw}** for `{pcr_t}`. "
                    "Nearest: " + ", ".join(f"`{d}`" for d in upcoming)
                )
                pcr_exp_date = None

            if pcr_exp_date:
                st.markdown(
                    f"#### {pcr_t}  ·  expiration **{pcr_exp_date}**"
                )

                with st.spinner("Summing calls and puts across all strikes…"):
                    pcr_stats = fetch_put_call_analysis(
                        pcr_t, pcr_exp_date, pcr_live_flag
                    )
                    pcr_calls, pcr_puts = get_option_chain(
                        pcr_t, pcr_exp_date, live_fetch=pcr_live_flag
                    )

                if pcr_stats is None:
                    if not pcr_live_flag:
                        st.warning(
                            f"No cached option chain for `{pcr_t}` exp "
                            f"{pcr_exp_date}. Tick **Fetch live data** and "
                            "click **Analyze** again."
                        )
                    else:
                        st.error("Empty option chain returned.")
                else:
                    s = pcr_stats
                    # Headline banner
                    if s["volume_winner"] == "Calls":
                        st.success(
                            f"📈 **Calls dominate** on volume for {pcr_t} "
                            f"exp {pcr_exp_date} — bullish lean."
                        )
                    elif s["volume_winner"] == "Puts":
                        st.error(
                            f"📉 **Puts dominate** on volume for {pcr_t} "
                            f"exp {pcr_exp_date} — bearish lean."
                        )
                    else:
                        st.info("Calls and puts are tied on volume — no clear lean.")

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Call volume", f"{s['call_volume']:,}")
                    m2.metric("Put volume", f"{s['put_volume']:,}")
                    m3.metric(
                        "Put/Call ratio (vol)",
                        f"{s['put_call_ratio_volume']:.2f}"
                        if s["put_call_ratio_volume"] is not None
                        else "—",
                        help="Puts ÷ calls by volume. >1 = puts dominate.",
                    )
                    m4.metric(
                        "Put/Call ratio (OI)",
                        f"{s['put_call_ratio_oi']:.2f}"
                        if s["put_call_ratio_oi"] is not None
                        else "—",
                        help="Puts ÷ calls by open interest.",
                    )

                    st.markdown(s["volume_verdict"])
                    st.markdown(s["oi_verdict"])

                    # Comparison table
                    cmp_df = pd.DataFrame(
                        [
                            {
                                "Metric": "Volume (contracts traded)",
                                "Calls": s["call_volume"],
                                "Puts": s["put_volume"],
                                "Dominates": s["volume_winner"],
                            },
                            {
                                "Metric": "Open interest (still open)",
                                "Calls": s["call_open_interest"],
                                "Puts": s["put_open_interest"],
                                "Dominates": s["oi_winner"],
                            },
                            {
                                "Metric": "Listed strikes",
                                "Calls": s["call_strikes"],
                                "Puts": s["put_strikes"],
                                "Dominates": "—",
                            },
                        ]
                    )
                    st.dataframe(
                        cmp_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Calls": st.column_config.NumberColumn(format="%d"),
                            "Puts": st.column_config.NumberColumn(format="%d"),
                        },
                    )

                    # Charts — volume & OI side by side
                    fig_pcr = make_subplots(
                        rows=1, cols=2,
                        subplot_titles=("Volume", "Open interest"),
                        specs=[[{"type": "bar"}, {"type": "bar"}]],
                    )
                    fig_pcr.add_trace(
                        go.Bar(
                            x=["Calls", "Puts"],
                            y=[s["call_volume"], s["put_volume"]],
                            marker_color=["#26a69a", "#ef5350"],
                            text=[f"{s['call_volume']:,}", f"{s['put_volume']:,}"],
                            textposition="outside",
                            name="Volume",
                        ),
                        row=1, col=1,
                    )
                    fig_pcr.add_trace(
                        go.Bar(
                            x=["Calls", "Puts"],
                            y=[s["call_open_interest"], s["put_open_interest"]],
                            marker_color=["#26a69a", "#ef5350"],
                            text=[
                                f"{s['call_open_interest']:,}",
                                f"{s['put_open_interest']:,}",
                            ],
                            textposition="outside",
                            name="Open interest",
                            showlegend=False,
                        ),
                        row=1, col=2,
                    )
                    fig_pcr.update_layout(
                        height=380,
                        margin=dict(l=10, r=10, t=40, b=10),
                        showlegend=False,
                    )
                    fig_pcr.update_yaxes(title_text="Contracts", row=1, col=1)
                    fig_pcr.update_yaxes(title_text="Contracts", row=1, col=2)
                    st.plotly_chart(fig_pcr, use_container_width=True)

                    # Top strikes by volume (where the action is)
                    st.markdown("#### Where is the action? — Top strikes by volume")
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        st.markdown("**Top call strikes**")
                        if pcr_calls is not None and not pcr_calls.empty and "volume" in pcr_calls.columns:
                            top_calls = (
                                pcr_calls[["strike", "volume", "openInterest", "lastPrice"]]
                                .sort_values("volume", ascending=False)
                                .head(10)
                                .reset_index(drop=True)
                            )
                            st.dataframe(
                                top_calls,
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    "strike": st.column_config.NumberColumn(format="$%.2f"),
                                    "volume": st.column_config.NumberColumn(format="%d"),
                                    "openInterest": st.column_config.NumberColumn("Open int", format="%d"),
                                    "lastPrice": st.column_config.NumberColumn("Last", format="$%.2f"),
                                },
                            )
                        else:
                            st.caption("No call volume data.")
                    with tc2:
                        st.markdown("**Top put strikes**")
                        if pcr_puts is not None and not pcr_puts.empty and "volume" in pcr_puts.columns:
                            top_puts = (
                                pcr_puts[["strike", "volume", "openInterest", "lastPrice"]]
                                .sort_values("volume", ascending=False)
                                .head(10)
                                .reset_index(drop=True)
                            )
                            st.dataframe(
                                top_puts,
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    "strike": st.column_config.NumberColumn(format="$%.2f"),
                                    "volume": st.column_config.NumberColumn(format="%d"),
                                    "openInterest": st.column_config.NumberColumn("Open int", format="%d"),
                                    "lastPrice": st.column_config.NumberColumn("Last", format="$%.2f"),
                                },
                            )
                        else:
                            st.caption("No put volume data.")

                    pcr_plain = (
                        f"{pcr_t} exp {pcr_exp_date} | "
                        f"Call vol: {s['call_volume']:,} | "
                        f"Put vol: {s['put_volume']:,} | "
                        f"Vol dominates: {s['volume_winner']} | "
                        f"P/C ratio (vol): "
                        f"{s['put_call_ratio_volume']:.2f} | "
                        f"Call OI: {s['call_open_interest']:,} | "
                        f"Put OI: {s['put_open_interest']:,} | "
                        f"OI dominates: {s['oi_winner']}"
                    )
                    with st.expander("📋 Copy summary (plain text)", expanded=False):
                        st.code(pcr_plain, language="text")


# --------------------------------------------------------------------------- #
# Cached Data tab — browse and re-view previously-fetched option contracts
# --------------------------------------------------------------------------- #
with tab_cached:
    st.markdown("### Cached Option Contracts")
    st.caption(
        "Every option contract you've previously fetched is saved on disk. "
        "Pick one from the list to re-view its recent activity — no network "
        "call required."
    )

    cached_contracts = list_cached_contracts()

    if not cached_contracts:
        st.info(
            "No cached option contracts on disk yet.\n\n"
            "Submit the form on the left with **Fetch live data** turned on "
            "to download a contract — it will then show up here for instant "
            "re-viewing in cache-only mode."
        )
    else:
        # Summary table
        cc_df = pd.DataFrame(
            [
                {
                    "Ticker": r["ticker"],
                    "Type": r["option_type"],
                    "Strike": r["strike"],
                    "Expiration": r["expiration"],
                    "Rows": r["num_rows"],
                    "Last bar": pd.Timestamp(r["last_bar_date"]).strftime("%Y-%m-%d"),
                    "Cached on": r["cache_updated_at"].strftime("%Y-%m-%d %H:%M"),
                    "Size (KB)": r["file_size_kb"],
                    "Contract symbol": r["contract_symbol"],
                }
                for r in cached_contracts
            ]
        )
        st.dataframe(
            cc_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Strike": st.column_config.NumberColumn(format="$%.2f"),
                "Rows": st.column_config.NumberColumn(format="%d"),
                "Size (KB)": st.column_config.NumberColumn(format="%.1f"),
                "Contract symbol": st.column_config.TextColumn(
                    help="OCC option symbol — used internally as the cache filename."
                ),
            },
        )

        # Friendly labels for the selectbox
        labels = {
            r["contract_symbol"]: (
                f"{r['ticker']} {r['option_type']} ${r['strike']:g} "
                f"exp {r['expiration']}  ·  {r['num_rows']} rows  ·  "
                f"cached {r['cache_updated_at']:%Y-%m-%d %H:%M}"
            )
            for r in cached_contracts
        }
        selected_symbol = st.selectbox(
            "Pick a contract to view",
            options=list(labels.keys()),
            format_func=lambda s: labels[s],
            key="cached_data_select",
        )

        # Render the selected contract
        sel = next(
            (r for r in cached_contracts if r["contract_symbol"] == selected_symbol),
            None,
        )
        if sel is not None:
            st.markdown(
                f"#### {sel['ticker']} {sel['option_type']} "
                f"${sel['strike']:g}  ·  exp {sel['expiration']}"
            )
            st.caption(
                f"Contract symbol: `{sel['contract_symbol']}`  ·  "
                f"Cached on disk · last updated "
                f"**{sel['cache_updated_at']:%Y-%m-%d %H:%M}**  ·  "
                f"{sel['num_rows']} rows  ·  last bar "
                f"**{pd.Timestamp(sel['last_bar_date']):%Y-%m-%d}**"
            )

            # Always read from disk (cache-only) — fast and avoids network.
            cached_hist = fcache.disk_cached_history(
                sel["contract_symbol"], live_fetch=False
            )
            # Underlying for both Stock Close alignment AND the weekly trend
            under_recent = fcache.disk_cached_history(
                sel["ticker"], live_fetch=False
            )
            cd_trend = (
                weekly_trend_note(sel["ticker"], under_recent)
                if under_recent is not None and not under_recent.empty
                else None
            )
            if cd_trend is not None:
                st.markdown(f"##### {sel['ticker']} weekly trend")
                if cd_trend["above_ma"]:
                    st.success(cd_trend["note"])
                else:
                    st.error(cd_trend["note"])
            elif under_recent is None or under_recent.empty:
                st.caption(
                    f"_No cached `{sel['ticker']}` underlying history on disk — "
                    "the weekly trend note can't be computed. Submit the form "
                    "for this ticker once in live mode to populate it._"
                )

            if cached_hist is None or cached_hist.empty:
                st.warning("Cache file exists but contains no rows.")
            else:
                ch = cached_hist.tail(30).copy()
                if ch.index.tz is not None:
                    ch.index = ch.index.tz_localize(None)

                # Try to enrich with the underlying stock close (cache-only)
                stock_close_aligned = pd.Series(index=ch.index, dtype=float)
                if under_recent is not None and not under_recent.empty:
                    stock_close_aligned = under_recent["Close"].reindex(
                        ch.index, method="ffill"
                    )

                cd_display = ch[["Open", "High", "Low", "Close", "Volume"]].copy()
                cd_display.insert(0, "Date", cd_display.index.strftime("%Y-%m-%d"))
                cd_display["Stock Close"] = stock_close_aligned.values
                cd_display = cd_display[
                    ["Date", "Open", "High", "Low", "Close", "Stock Close", "Volume"]
                ].reset_index(drop=True)

                def _hl(col: pd.Series) -> list[str]:
                    valid = col.dropna()
                    if valid.empty or valid.max() == valid.min():
                        return [""] * len(col)
                    cmax, cmin = valid.max(), valid.min()
                    out = []
                    for v in col:
                        if pd.isna(v):
                            out.append("")
                        elif v == cmax:
                            out.append(
                                "background-color: #1e88e5; color: white; "
                                "font-weight: 600"
                            )
                        elif v == cmin:
                            out.append(
                                "background-color: #e53935; color: white; "
                                "font-weight: 600"
                            )
                        else:
                            out.append("")
                    return out

                styled = (
                    cd_display.style
                    .apply(_hl, subset=["Stock Close"])
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
                st.markdown("##### Last 30 trading sessions")
                st.dataframe(
                    styled,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Date": st.column_config.TextColumn("Date"),
                        "Open": st.column_config.NumberColumn("Option Open"),
                        "High": st.column_config.NumberColumn("Option High"),
                        "Low": st.column_config.NumberColumn("Option Low"),
                        "Close": st.column_config.NumberColumn("Option Close"),
                        "Stock Close": st.column_config.NumberColumn(
                            f"{sel['ticker']} Close",
                            help=(
                                f"{sel['ticker']}'s closing stock price on that "
                                "day. Highest = blue, lowest = red. Underlying "
                                "must also be cached on disk."
                            ),
                        ),
                        "Volume": st.column_config.NumberColumn("Volume"),
                    },
                )

                # Chart
                fig_c = make_subplots(
                    rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.75, 0.25], vertical_spacing=0.05,
                    subplot_titles=("Price (Candlestick + Close)", "Volume"),
                )
                fig_c.add_trace(
                    go.Candlestick(
                        x=ch.index, open=ch["Open"], high=ch["High"],
                        low=ch["Low"], close=ch["Close"], name="OHLC",
                        increasing_line_color="#26a69a",
                        decreasing_line_color="#ef5350",
                    ),
                    row=1, col=1,
                )
                fig_c.add_trace(
                    go.Scatter(
                        x=ch.index, y=ch["Close"],
                        mode="lines+markers", name="Close",
                        line=dict(color="#42a5f5", width=2),
                        marker=dict(size=6),
                        hovertemplate=(
                            "<b>%{x|%Y-%m-%d}</b><br>"
                            "Close: $%{y:.2f}<extra></extra>"
                        ),
                    ),
                    row=1, col=1,
                )
                fig_c.add_trace(
                    go.Bar(
                        x=ch.index, y=ch["Volume"], name="Volume",
                        marker_color="#90a4ae",
                        hovertemplate=(
                            "<b>%{x|%Y-%m-%d}</b><br>"
                            "Volume: %{y:,}<extra></extra>"
                        ),
                    ),
                    row=2, col=1,
                )
                fig_c.update_layout(
                    height=560, hovermode="x unified",
                    xaxis_rangeslider_visible=False,
                    showlegend=True,
                    legend=dict(
                        orientation="h", yanchor="bottom",
                        y=1.02, xanchor="right", x=1,
                    ),
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                fig_c.update_yaxes(title_text="Price (USD)", row=1, col=1)
                fig_c.update_yaxes(title_text="Volume", row=2, col=1)
                fig_c.update_xaxes(
                    rangebreaks=[dict(bounds=["sat", "mon"])], row=2, col=1,
                )
                st.plotly_chart(fig_c, use_container_width=True)

                # One-click "load this into the sidebar form" — populates the
                # form widgets via session_state and reruns so the user can run
                # forecasts / what-if on this contract without retyping.
                if st.button(
                    "Load this contract into the sidebar form",
                    key="load_cached_into_form",
                    use_container_width=False,
                    help=(
                        "Pre-fills the sidebar with this contract's ticker, "
                        "type, MM/DD expiration, and strike — then you can "
                        "click Fetch Data to run forecasts/what-if on it."
                    ),
                ):
                    exp_dt = datetime.strptime(sel["expiration"], "%Y-%m-%d")
                    st.session_state["fetch_inputs"] = {
                        "ticker": sel["ticker"],
                        "option_type": sel["option_type"],
                        "expiration_input": exp_dt.strftime("%m/%d"),
                        "mm": exp_dt.month,
                        "dd": exp_dt.day,
                        "strike": float(sel["strike"]),
                    }
                    st.rerun()


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
    for _t in (tab_recent, tab_forecast, tab_whatif):
        with _t:
            st.info(
                "Fill in the form on the left (ticker, option type, "
                "expiration, strike) and click **Fetch Data** to load this tab. "
                "The **Track the Best**, **Quick Summary**, **Check SMA**, "
                "**Calls vs Puts**, and **Cached Data** tabs work independently "
                "and are already populated above."
            )
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
        expirations = get_expirations(ticker, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001 — surface any yfinance error to user
        st.error(f"Could not fetch options for `{ticker}`: {exc}")
        st.stop()

if not expirations:
    if not live_fetch:
        st.warning(
            f"No cached expirations on disk for `{ticker}`. "
            "Tick **Fetch live data** in the sidebar to download them, then re-submit."
        )
    else:
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
        calls, puts = get_option_chain(ticker, expiration_date, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load option chain: {exc}")
        st.stop()

chain_df = calls if option_type == "Call" else puts
if chain_df is None or chain_df.empty:
    if not live_fetch:
        st.warning(
            f"No cached option chain on disk for `{ticker}` exp {expiration_date}. "
            "Tick **Fetch live data** in the sidebar to download it, then re-submit."
        )
    else:
        st.error(f"Empty option chain returned for {ticker} {expiration_date}.")
    st.stop()

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
        hist = get_contract_history(contract_symbol, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch contract history: {exc}")
        st.stop()

if hist is None or hist.empty:
    if not live_fetch:
        st.warning(
            f"No cached history on disk for contract `{contract_symbol}`. "
            "Tick **Fetch live data** in the sidebar to download ~3 months of "
            "history for this contract, then re-submit. After that you can "
            "uncheck the box again to keep using the cache."
        )
    else:
        st.warning(
            "No historical price data available for this contract. "
            "It may be illiquid or newly listed. Try a different strike or expiration."
        )
    st.stop()

# --- Data-update badge — last cache write time + live/cache mode ---------- #
contract_badge = format_cache_badge(contract_symbol, live_fetch=live_fetch)
underlying_meta = fcache.cache_metadata(ticker)
if contract_badge:
    if live_fetch:
        st.success(":satellite: " + contract_badge)
    else:
        st.info(":package: " + contract_badge)
    if underlying_meta:
        st.caption(
            f"Underlying `{ticker}` cache last updated "
            f"{underlying_meta['cache_updated_at']:%Y-%m-%d %H:%M} "
            f"(last bar {underlying_meta['last_bar_date']:%Y-%m-%d}, "
            f"{underlying_meta['num_rows']} rows)."
        )

hist = hist.tail(30).copy()
hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index


# --------------------------------------------------------------------------- #
# Tab content — tabs were defined up-front near the title.
# --------------------------------------------------------------------------- #
with tab_recent:
    # Pull 1y of underlying history once — used for both the "Stock Close"
    # column alignment AND the weekly trend note (the latter needs ~5 months
    # of weekly bars).
    underlying_recent: pd.DataFrame | None = None
    try:
        underlying_recent = get_underlying_history(
            ticker, period="1y", live_fetch=live_fetch
        )
    except Exception:
        underlying_recent = None

    # Weekly-trend note for the underlying (above 20-week MA, streak, 52-wk high)
    trend = (
        weekly_trend_note(ticker, underlying_recent)
        if underlying_recent is not None and not underlying_recent.empty
        else None
    )
    if trend is not None:
        st.markdown(f"#### {ticker} weekly trend")
        if trend["above_ma"]:
            st.success(trend["note"])
        else:
            st.error(trend["note"])

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
    if underlying_recent is not None and not underlying_recent.empty:
        stock_close_aligned = underlying_recent["Close"].reindex(
            hist.index, method="ffill"
        )

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
            underlying = get_underlying_history(
                ticker, period="1y", live_fetch=live_fetch
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not fetch underlying history for `{ticker}`: {exc}")
            st.stop()

    if underlying is None or underlying.empty or len(underlying) < 60:
        if not live_fetch:
            st.warning(
                f"Not enough cached underlying history for `{ticker}` to run "
                "forecasts (need ~60 trading days). Tick **Fetch live data** in "
                "the sidebar to download ~1 year of history, then re-submit."
            )
        else:
            st.warning(
                "Not enough underlying history to run forecasts (need ~60 trading "
                "days). Skipping the Forecasts section."
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

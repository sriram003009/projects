"""Business logic extracted from the Streamlit app (no UI dependencies)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List

import pandas as pd

import cache as fcache
import forecasting as fc
from services.data_access import get_option_chain

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
        "Overall Trend": "No cached data — enable Fetch live data",
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



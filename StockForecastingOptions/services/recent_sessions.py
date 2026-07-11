"""Last N trading sessions with OHLC and prior close for change highlighting."""

from __future__ import annotations

from typing import Any

import pandas as pd

import cache as fcache
from services.contract_service import ServiceError
from services.data_access import get_underlying_history
from services.messages import cache_miss_message
from services.serialize import clean_dict
from services.session_helpers import enrich_current_session_rows

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_recent_sessions(
    ticker: str,
    *,
    sessions: int = 20,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Return the last *sessions* daily bars with Open, High, Low, Close."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise ServiceError("missing_ticker", "Enter a stock ticker.")

    sessions = max(1, min(int(sessions), 60))

    try:
        df = get_underlying_history(ticker, period="3mo", live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("history_failed", f"Could not load history for `{ticker}`: {exc}") from exc

    if df is None or df.empty:
        if not live_fetch:
            raise ServiceError(
                "no_cached_history",
                cache_miss_message("price history", ticker=ticker),
            )
        raise ServiceError("no_history", f"No price history available for `{ticker}`.")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ServiceError("invalid_history", f"Unexpected index type for `{ticker}`.")

    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        raise ServiceError("invalid_history", f"OHLC columns missing for `{ticker}`.")

    df = df.sort_index()
    prev_close_series = df["Close"].shift(1)
    subset = df.tail(sessions)

    if subset.empty:
        raise ServiceError(
            "no_recent_sessions",
            f"No recent sessions found for `{ticker}` in cached history.",
        )

    rows: list[dict] = []
    for dt, row in subset.iterrows():
        prev = prev_close_series.loc[dt]
        rows.append(
            {
                "Date": dt.strftime("%Y-%m-%d"),
                "Weekday": WEEKDAY_LABELS[dt.weekday()],
                "Open": float(row["Open"]),
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"]),
                "Prev Close": float(prev) if pd.notna(prev) else None,
            }
        )

    rows = enrich_current_session_rows(rows, ticker=ticker, live_fetch=live_fetch)

    meta = fcache.cache_metadata(ticker)

    return clean_dict(
        {
            "ticker": ticker,
            "sessions_requested": sessions,
            "sessions_returned": len(rows),
            "live_fetch": live_fetch,
            "data_source": "live" if live_fetch else "cache",
            "cache_meta": meta,
            "rows": rows,
        }
    )

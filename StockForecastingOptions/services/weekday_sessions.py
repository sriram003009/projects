"""Last N trading sessions for a chosen weekday (Mon–Fri) with OHLC + prev close."""

from __future__ import annotations

from typing import Any

import pandas as pd

import cache as fcache
from services.contract_service import ServiceError
from services.data_access import get_underlying_history
from services.messages import cache_miss_message
from services.serialize import clean_dict

WEEKDAY_NAMES: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
}

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _normalize_weekday(weekday: str | int) -> tuple[int, str]:
    if isinstance(weekday, int):
        if weekday < 0 or weekday > 4:
            raise ServiceError("invalid_weekday", "Weekday must be 0–4 (Mon–Fri).")
        return weekday, WEEKDAY_LABELS[weekday]

    key = weekday.strip().lower()
    if key not in WEEKDAY_NAMES:
        raise ServiceError(
            "invalid_weekday",
            "Weekday must be Monday, Tuesday, Wednesday, Thursday, or Friday.",
        )
    idx = WEEKDAY_NAMES[key]
    return idx, WEEKDAY_LABELS[idx]


def get_weekday_sessions(
    ticker: str,
    weekday: str | int,
    *,
    sessions: int = 10,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Return the last *sessions* bars that fall on *weekday* (Mon=0 … Fri=4)."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise ServiceError("missing_ticker", "Enter a stock ticker.")

    wd_idx, wd_label = _normalize_weekday(weekday)
    sessions = max(1, min(int(sessions), 52))

    try:
        df = get_underlying_history(ticker, period="2y", live_fetch=live_fetch)
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

    mask = df.index.weekday == wd_idx
    subset = df.loc[mask].tail(sessions)

    if subset.empty:
        raise ServiceError(
            "no_weekday_sessions",
            f"No {wd_label} sessions found for `{ticker}` in cached history.",
        )

    rows: list[dict] = []
    for dt, row in subset.iterrows():
        prev = prev_close_series.loc[dt]
        rows.append(
            {
                "Date": dt.strftime("%Y-%m-%d"),
                "Weekday": wd_label,
                "Prev Close": float(prev) if pd.notna(prev) else None,
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"]),
            }
        )

    meta = fcache.cache_metadata(ticker)

    return clean_dict(
        {
            "ticker": ticker,
            "weekday": wd_label,
            "weekday_index": wd_idx,
            "sessions_requested": sessions,
            "sessions_returned": len(rows),
            "live_fetch": live_fetch,
            "data_source": "live" if live_fetch else "cache",
            "cache_meta": meta,
            "rows": rows,
        }
    )

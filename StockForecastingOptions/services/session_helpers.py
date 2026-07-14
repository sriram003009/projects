"""Shared helpers for session tables (weekday / recent) — live today row."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import yfinance as yf

import cache as fcache


def today_session_date() -> str:
    return pd.Timestamp(dt.date.today()).strftime("%Y-%m-%d")


def fetch_live_last_price(ticker: str) -> float | None:
    """Latest traded price from Yahoo (regular session when available)."""
    try:
        t = yf.Ticker(ticker)
        fast = getattr(t, "fast_info", None)
        if fast is not None:
            for attr in ("last_price", "lastPrice"):
                val = getattr(fast, attr, None)
                if val is not None and not pd.isna(val):
                    return float(val)
        info = t.info or {}
        for key in ("regularMarketPrice", "currentPrice"):
            val = info.get(key)
            if val is not None and not pd.isna(val):
                return float(val)
    except Exception:  # noqa: BLE001
        pass
    return None


def enrich_current_session_rows(
    rows: list[dict[str, Any]],
    *,
    ticker: str,
    live_fetch: bool,
) -> list[dict[str, Any]]:
    """Tag today's row; refresh Close/High/Low live only during market hours."""
    if not rows:
        return rows

    today = today_session_date()
    live_now = fcache.should_live_refresh(live_fetch)
    live_price = fetch_live_last_price(ticker) if live_now else None
    enriched: list[dict[str, Any]] = []

    for row in rows:
        out = dict(row)
        is_today = out.get("Date") == today
        out["Is Current Session"] = is_today
        out["Row Source"] = (
            "live"
            if is_today and live_now and live_price is not None
            else "cache"
            if is_today
            else "historical"
        )

        if is_today and live_now and live_price is not None:
            out["Close"] = live_price
            if "High" in out and live_price > out["High"]:
                out["High"] = live_price
            if "Low" in out and live_price < out["Low"]:
                out["Low"] = live_price

        enriched.append(out)

    return enriched

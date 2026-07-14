"""User-managed 'stocks to watch tomorrow' list with 50/200-day MA signals."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import cache as fcache
from services import analytics as biz
from services.contract_service import ServiceError
from services.data_access import data_source_label
from services.messages import LIVE_FETCH_HINT
from services.serialize import clean_dict, df_to_records

WATCHLIST_FILE = fcache.CACHE_DIR / "tomorrow_watchlist.json"
TICKER_RE = re.compile(r"^\^?[A-Z][A-Z0-9.\-]{0,15}$")


def _load_raw() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with WATCHLIST_FILE.open() as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            items = payload.get("items", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        return [i for i in items if isinstance(i, dict) and i.get("symbol")]
    except Exception:
        return []


def _save_raw(items: list[dict]) -> None:
    WATCHLIST_FILE.parent.mkdir(exist_ok=True)
    with WATCHLIST_FILE.open("w") as f:
        json.dump(
            {
                "items": items,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )


def list_symbols() -> list[str]:
    return [str(i["symbol"]).upper() for i in _load_raw()]


def add_symbol(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ServiceError("missing_ticker", "Enter a ticker symbol.")
    if not TICKER_RE.match(symbol):
        raise ServiceError(
            "invalid_ticker",
            f"Invalid ticker `{symbol}`. Use letters only (e.g. NVDA, AAPL, ^SPX).",
        )

    items = _load_raw()
    if any(str(i["symbol"]).upper() == symbol for i in items):
        raise ServiceError("duplicate_ticker", f"`{symbol}` is already on your watchlist.")

    items.append(
        {
            "symbol": symbol,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_raw(items)
    return {"symbol": symbol, "symbols": list_symbols()}


def remove_symbol(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    items = _load_raw()
    kept = [i for i in items if str(i["symbol"]).upper() != symbol]
    if len(kept) == len(items):
        raise ServiceError("not_found", f"`{symbol}` is not on your watchlist.")
    _save_raw(kept)
    return {"symbol": symbol, "symbols": list_symbols()}


def get_watchlist_analysis(live_fetch: bool = False) -> dict[str, Any]:
    """Return watchlist rows with 50/200 SMA and Bullish/Bearish MA signal."""
    symbols = list_symbols()
    rows: list[dict] = []
    missing: list[str] = []

    for symbol in symbols:
        try:
            df = fcache.disk_cached_history(
                symbol, min_period="1y", live_fetch=live_fetch
            )
        except Exception:
            df = None

        if df is None or df.empty:
            if not live_fetch:
                missing.append(symbol)

        row = biz.build_sma_check_row(symbol, df)
        row["MA Signal"] = biz.ma_signal_label(
            row.get("_above_50"), row.get("_above_200")
        )
        rows.append(row)

    display_rows: list[dict] = []
    for row in rows:
        display_rows.append(
            {
                "Stock": row["Stock"],
                "Price (approx.)": row["Price (approx.)"],
                "50-day SMA price": row["50-day SMA price"],
                "vs 50-day SMA": row["vs 50-day SMA"],
                "200-day SMA price": row["200-day SMA price"],
                "vs 200-day SMA": row["vs 200-day SMA"],
                "MA Signal": row["MA Signal"],
                "Overall Trend": row["Overall Trend"],
            }
        )

    cache_hint = None
    if not live_fetch and missing:
        cache_hint = (
            f"No cached data for: {', '.join(missing)}."
            + LIVE_FETCH_HINT
        )

    return clean_dict(
        {
            "symbols": symbols,
            "live_fetch": live_fetch,
            "data_source": data_source_label(live_fetch),
            "cache_hint": cache_hint,
            "rows": display_rows,
            "raw": df_to_records(
                pd.DataFrame(rows).drop(
                    columns=["_above_50", "_above_200"], errors="ignore"
                )
                if rows
                else pd.DataFrame()
            ),
        }
    )

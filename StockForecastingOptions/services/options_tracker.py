"""User-tracked option positions (calls/puts) with entry vs current price."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

import cache as fcache
from services import analytics as biz
from services.contract_service import ServiceError
from services.data_access import data_source_label, get_expirations, get_option_chain

TRACKER_FILE = fcache.CACHE_DIR / "options_tracker.json"


def _load_raw() -> list[dict]:
    if not TRACKER_FILE.exists():
        return []
    try:
        with TRACKER_FILE.open() as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            items = payload.get("items", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        return [i for i in items if isinstance(i, dict) and i.get("id")]
    except Exception:
        return []


def _save_raw(items: list[dict]) -> None:
    TRACKER_FILE.parent.mkdir(exist_ok=True)
    with TRACKER_FILE.open("w") as f:
        json.dump(
            {
                "items": items,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )


def _chain_last_price(
    ticker: str,
    option_type: Literal["Call", "Put"],
    expiration_date: str,
    strike: float,
    live_fetch: bool,
) -> float | None:
    try:
        calls, puts = get_option_chain(ticker, expiration_date, live_fetch=live_fetch)
    except Exception:
        return None
    chain = calls if option_type == "Call" else puts
    if chain is None or chain.empty or "strike" not in chain.columns:
        return None
    match = chain[chain["strike"].round(4) == round(strike, 4)]
    if match.empty:
        return None
    row = match.iloc[0]
    val = row.get("lastPrice")
    if pd.isna(val):
        return None
    return float(val)


def add_position(
    *,
    ticker: str,
    option_type: Literal["Call", "Put"],
    expiration_mmdd: str,
    strike: float,
    entry_price: float | None = None,
    live_fetch: bool = False,
) -> dict[str, Any]:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ServiceError("missing_ticker", "Enter a stock ticker.")
    if strike <= 0:
        raise ServiceError("invalid_strike", "Strike must be greater than zero.")

    try:
        mm, dd, year = biz.parse_expiration_input(expiration_mmdd.strip())
    except ValueError:
        raise ServiceError("invalid_expiration", biz.EXPIRATION_FORMAT_MSG)

    try:
        expirations = get_expirations(ticker, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("expirations_failed", str(exc)) from exc

    if not expirations:
        code = "no_cached_expirations" if not live_fetch else "no_options"
        raise ServiceError(code, f"No expirations listed for `{ticker}`.")

    try:
        expiration_date = biz.resolve_expiration(mm, dd, expirations, year=year)
    except ValueError:
        raise ServiceError(
            "expiration_not_found",
            f"No expiration matches {expiration_mmdd} for `{ticker}`.",
            {"nearest": biz.nearest_expirations(expirations)},
        )

    price = entry_price
    if price is None:
        price = _chain_last_price(ticker, option_type, expiration_date, strike, live_fetch)
    if price is None or price <= 0:
        raise ServiceError(
            "no_entry_price",
            "Could not read option price — enable Fetch live data or enter entry price manually.",
        )

    item = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "option_type": option_type,
        "expiration_input": expiration_mmdd.strip(),
        "expiration_date": expiration_date,
        "strike": float(strike),
        "entry_price": round(float(price), 4),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_raw()
    items.append(item)
    _save_raw(items)
    return {"id": item["id"], "count": len(items)}


def remove_position(position_id: str) -> dict[str, Any]:
    pid = position_id.strip()
    items = _load_raw()
    kept = [i for i in items if str(i.get("id")) != pid]
    if len(kept) == len(items):
        raise ServiceError("not_found", "Position not found.")
    _save_raw(kept)
    return {"id": pid, "count": len(kept)}


def _enrich_row(item: dict, *, live_fetch: bool) -> dict[str, Any]:
    ticker = str(item["ticker"]).upper()
    option_type = item["option_type"]
    expiration_date = str(item["expiration_date"])
    strike = float(item["strike"])
    entry = float(item["entry_price"])

    current = _chain_last_price(ticker, option_type, expiration_date, strike, live_fetch)
    change_abs: float | None = None
    change_pct: float | None = None
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"

    if current is not None:
        change_abs = round(current - entry, 4)
        change_pct = round((change_abs / entry) * 100.0, 2) if entry else None
        if change_abs > 0.0001:
            direction = "up"
        elif change_abs < -0.0001:
            direction = "down"
        else:
            direction = "flat"

    return {
        "id": item["id"],
        "ticker": ticker,
        "option_type": option_type,
        "expiration_input": item.get("expiration_input"),
        "expiration_date": expiration_date,
        "strike": strike,
        "entry_price": entry,
        "added_at": item.get("added_at"),
        "current_price": round(current, 4) if current is not None else None,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "direction": direction,
        "price_unavailable": current is None,
    }


def list_positions(live_fetch: bool = False) -> dict[str, Any]:
    items = _load_raw()
    rows = [_enrich_row(i, live_fetch=live_fetch) for i in items]
    missing = [r["ticker"] for r in rows if r["price_unavailable"]]
    cache_hint = None
    if not live_fetch and missing:
        cache_hint = (
            f"No cached price for: {', '.join(sorted(set(missing)))}. "
            "Enable Fetch live data and refresh."
        )
    return {
        "live_fetch": live_fetch,
        "data_source": data_source_label(live_fetch),
        "cache_hint": cache_hint,
        "count": len(rows),
        "rows": rows,
    }

"""Floor-trader pivot levels (PP, R1–R3, S1–S3) from prior session H/L/C."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

import cache as fcache
from services.contract_service import ServiceError
from services.data_access import get_underlying_history
from services.messages import cache_miss_message
from services.serialize import clean_dict
from services.session_helpers import fetch_live_last_price, today_session_date

LevelKind = Literal["resistance", "pivot", "support"]


def _floor_trader_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Classic floor-trader formulas (PP = (H+L+C)/3)."""
    pp = (high + low + close) / 3.0
    return {
        "PP": pp,
        "R1": 2.0 * pp - low,
        "R2": pp + (high - low),
        "R3": high + 2.0 * (pp - low),
        "S1": 2.0 * pp - high,
        "S2": pp - (high - low),
        "S3": low - 2.0 * (high - pp),
    }


def _session_row(dt: pd.Timestamp, row: pd.Series) -> dict[str, Any]:
    return {
        "Date": dt.strftime("%Y-%m-%d"),
        "Weekday": dt.strftime("%A"),
        "Open": float(row["Open"]),
        "High": float(row["High"]),
        "Low": float(row["Low"]),
        "Close": float(row["Close"]),
    }


def _near(a: float, b: float, *, pct: float = 0.0015) -> bool:
    """Within ~0.15% — 'defended to the dime' at a level."""
    return abs(a - b) <= max(abs(b) * pct, 0.05)


def _level_interaction(
    price: float,
    kind: LevelKind,
    today: dict[str, float],
) -> str | None:
    """Short tag for how today's range interacted with a level."""
    o, h, l, c = today["Open"], today["High"], today["Low"], today["Close"]

    if kind == "pivot":
        if l < price < h:
            if _near(c, price):
                return "closed at pivot"
            if c < price and h >= price:
                return "sold through pivot"
            if c > price and l <= price:
                return "reclaimed pivot"
            return "crossed pivot"
        if _near(c, price):
            return "closed at pivot"
        return None

    if kind == "resistance":
        if h >= price and c < price:
            return "rejected"
        if h >= price and c >= price:
            return "broke above"
        if _near(h, price):
            return "tested high"
        if h < price - 0.05:
            return "not reached"
        return None

    # support
    if l <= price and c > price:
        return "held — closed above"
    if l <= price and c <= price:
        return "broke below"
    if _near(l, price):
        return "tested low"
    if _near(c, price):
        return "closed at level"
    if l > price + 0.05:
        return "not reached"
    return None


def _build_level_ladder(
    *,
    pivots: dict[str, float],
    prior: dict[str, Any],
    prior_2: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge calculated pivots with prior-day H/L/C (and optional prior-2 low)."""
    entries: list[tuple[str, float, LevelKind, str]] = [
        ("R3", pivots["R3"], "resistance", "Floor trader R3"),
        ("R2", pivots["R2"], "resistance", "Floor trader R2"),
        (
            "Prior High",
            prior["High"],
            "resistance",
            f"{prior['Weekday']} high ({prior['Date']})",
        ),
        ("R1", pivots["R1"], "resistance", "Floor trader R1"),
        ("PP", pivots["PP"], "pivot", "Pivot — (H+L+C)/3"),
        (
            "Prior Close",
            prior["Close"],
            "support",
            f"{prior['Weekday']} close ({prior['Date']})",
        ),
        ("S1", pivots["S1"], "support", "Floor trader S1"),
        (
            "Prior Low",
            prior["Low"],
            "support",
            f"{prior['Weekday']} low ({prior['Date']})",
        ),
        ("S2", pivots["S2"], "support", "Floor trader S2"),
        ("S3", pivots["S3"], "support", "Floor trader S3"),
    ]

    if prior_2 is not None:
        entries.append(
            (
                "Prior-2 Low",
                prior_2["Low"],
                "support",
                f"{prior_2['Weekday']} low ({prior_2['Date']})",
            )
        )

    # De-dupe prices within 2 cents — combine labels
    entries.sort(key=lambda x: x[1], reverse=True)
    merged: list[dict[str, Any]] = []
    for name, price, kind, note in entries:
        if merged and abs(merged[-1]["Price"] - price) < 0.02:
            merged[-1]["Label"] = f"{merged[-1]['Label']} / {name}"
            merged[-1]["Notes"] = f"{merged[-1]['Notes']}; {note}"
            continue
        merged.append(
            {
                "Label": name,
                "Price": round(price, 2),
                "Kind": kind,
                "Notes": note,
            }
        )

    return merged


def _next_level_above(
    close: float, levels: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Nearest ladder level strictly above *close* (next ceiling to watch)."""
    above = [lv for lv in levels if lv["Price"] > close + 0.005]
    if not above:
        return None
    nxt = min(above, key=lambda x: x["Price"])
    dist = nxt["Price"] - close
    pct = (dist / close * 100.0) if close else 0.0
    return {
        "Label": nxt["Label"],
        "Price": nxt["Price"],
        "Kind": nxt["Kind"],
        "Distance": round(dist, 2),
        "Distance Pct": round(pct, 2),
    }


def _today_summary(today: dict[str, Any], levels: list[dict[str, Any]]) -> list[str]:
    """Plain-English bullets for today's action vs the ladder."""
    if not today:
        return []

    h, l, c = today["High"], today["Low"], today["Close"]
    lines: list[str] = []

    resistances = [lv for lv in levels if lv["Kind"] == "resistance"]
    supports = [lv for lv in levels if lv["Kind"] == "support"]
    pivot = next((lv for lv in levels if lv["Kind"] == "pivot"), None)

    if resistances:
        touched = [lv for lv in resistances if h >= lv["Price"]]
        if touched:
            top = max(touched, key=lambda x: x["Price"])
            lines.append(
                f"High {h:,.2f} pushed into resistance near {top['Label']} ({top['Price']:,.2f})."
            )

    if pivot and l < pivot["Price"] < h:
        lines.append(
            f"Session crossed the pivot at {pivot['Price']:,.2f} "
            f"(low {l:,.2f}, close {c:,.2f})."
        )

    broken = [lv for lv in supports if l <= lv["Price"]]
    if broken:
        deepest = min(broken, key=lambda x: x["Price"])
        lines.append(
            f"Low {l:,.2f} broke through support at {deepest['Label']} ({deepest['Price']:,.2f})."
        )

    if supports:
        nearest = min(supports, key=lambda lv: abs(lv["Price"] - c))
        if _near(c, nearest["Price"]):
            lines.append(
                f"Closed {c:,.2f} — right at {nearest['Label']} ({nearest['Price']:,.2f})."
            )
        elif c > nearest["Price"]:
            lines.append(
                f"Closed {c:,.2f} above nearest support {nearest['Label']} ({nearest['Price']:,.2f})."
            )

    nxt = _next_level_above(c, levels)
    if nxt:
        kind_hint = "resistance" if nxt["Kind"] == "resistance" else nxt["Kind"]
        lines.append(
            f"Next {kind_hint} to watch: {nxt['Label']} at {nxt['Price']:,.2f} "
            f"({nxt['Distance']:,.2f} / {nxt['Distance Pct']:+.2f}% above close)."
        )
    else:
        lines.append(
            f"Next resistance to watch: none on ladder — close {c:,.2f} is above all listed levels."
        )

    return lines


def get_pivot_levels(
    ticker: str,
    *,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Pivot ladder for *today* from prior session H/L/C (+ today's OHLC)."""
    raw = ticker.strip()
    if not raw:
        raise ServiceError("missing_ticker", "Enter a ticker (e.g. ^GSPC for SPX).")

    # Yahoo: ^GSPC = S&P 500 index; SPX also works for many feeds
    symbol = raw.upper()
    if symbol == "SPX":
        symbol = "^GSPC"

    try:
        df = get_underlying_history(symbol, period="3mo", live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("history_failed", f"Could not load history for `{symbol}`: {exc}") from exc

    if df is None or df.empty:
        if not live_fetch:
            raise ServiceError(
                "no_cached_history",
                cache_miss_message("price history", ticker=symbol),
            )
        raise ServiceError("no_history", f"No price history available for `{symbol}`.")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ServiceError("invalid_history", f"Unexpected index type for `{symbol}`.")

    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        raise ServiceError("invalid_history", f"OHLC columns missing for `{symbol}`.")

    df = df.sort_index()
    if len(df) < 2:
        raise ServiceError("no_history", f"Need at least 2 sessions for `{symbol}`.")

    today_str = today_session_date()
    last_dt = df.index.max().normalize()
    has_today = last_dt.strftime("%Y-%m-%d") == today_str

    if has_today and len(df) >= 3:
        prior_dt = df.index[-2]
        prior_2_dt = df.index[-3]
        today_dt = df.index[-1]
    elif has_today:
        prior_dt = df.index[-2]
        prior_2_dt = None
        today_dt = df.index[-1]
    else:
        prior_dt = df.index[-1]
        prior_2_dt = df.index[-2] if len(df) >= 2 else None
        today_dt = None

    prior = _session_row(prior_dt, df.loc[prior_dt])
    prior_2 = (
        _session_row(prior_2_dt, df.loc[prior_2_dt]) if prior_2_dt is not None else None
    )

    pivots = _floor_trader_pivots(prior["High"], prior["Low"], prior["Close"])
    levels = _build_level_ladder(pivots=pivots, prior=prior, prior_2=prior_2)

    today: dict[str, Any] | None = None
    if today_dt is not None:
        today = _session_row(today_dt, df.loc[today_dt])
        today["Is Current Session"] = True
        today["Row Source"] = "cache"
        if live_fetch:
            live = fetch_live_last_price(symbol)
            today["Row Source"] = "live"
            if live is not None:
                today["Close"] = live
                if live > today["High"]:
                    today["High"] = live
                if live < today["Low"]:
                    today["Low"] = live

        for lv in levels:
            tag = _level_interaction(
                lv["Price"],
                lv["Kind"],  # type: ignore[arg-type]
                today,  # type: ignore[arg-type]
            )
            if tag:
                lv["Today"] = tag

    meta = fcache.cache_metadata(symbol)
    display = "SPX" if symbol == "^GSPC" else symbol

    next_resistance = (
        _next_level_above(today["Close"], levels)
        if today
        else None
    )

    return clean_dict(
        {
            "ticker": symbol,
            "display_name": display,
            "formula": "PP = (Prior High + Prior Low + Prior Close) / 3",
            "session_date": today_str if has_today else None,
            "prior_session": prior,
            "prior_2_session": prior_2,
            "pivots": {k: round(v, 2) for k, v in pivots.items()},
            "levels": levels,
            "today": today,
            "next_resistance": next_resistance,
            "summary_lines": _today_summary(today, levels) if today else [],
            "live_fetch": live_fetch,
            "data_source": "live" if live_fetch else "cache",
            "cache_meta": meta,
        }
    )

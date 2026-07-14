"""Gamma exposure (GEX) by strike from option chains — dealer-style aggregation."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

import forecasting as fc
from services.contract_service import ServiceError
from services.data_access import (
    data_source_label,
    get_expirations,
    get_option_chain,
    get_underlying_history,
    should_live_refresh,
)
from services.messages import cache_miss_message
from services.serialize import clean_dict
from services.session_helpers import fetch_live_last_price

ExpirationFilter = Literal["all", "0dte", "nearest", "custom"]
GexRegime = Literal["Positive Gamma", "Neutral Gamma", "Negative Gamma"]

CONTRACT_MULT = 100
MAX_EXPIRATIONS_ALL = 16
REGIME_NEUTRAL_BAND = 0.05  # |net| within 5% of |call|+|put| sum → neutral


def _parse_expiration(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _time_to_expiry_years(exp: date, today: date) -> float:
    days = max((exp - today).days, 0)
    return max(days / 365.25, 1.0 / (365.25 * 24))


def _gex_dollars_per_1pct(gamma: float, oi: float, spot: float, *, sign: float) -> float:
    """Dealer GEX: dollars hedging flow per 1% move in spot (call +, put -)."""
    if oi <= 0 or gamma <= 0 or spot <= 0:
        return 0.0
    return float(sign * gamma * oi * CONTRACT_MULT * spot * spot * 0.01)


def _safe_iv(raw: Any) -> float | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    try:
        iv = float(raw)
    except (TypeError, ValueError):
        return None
    if iv <= 0 or iv > 5:
        return None
    return iv


def _chain_gex_by_strike(
    calls: pd.DataFrame | None,
    puts: pd.DataFrame | None,
    *,
    spot: float,
    exp: date,
    today: date,
) -> tuple[dict[float, float], dict[float, float], dict[float, float]]:
    """Return call_gex, put_gex, net_gex dicts keyed by strike."""
    call_by: dict[float, float] = {}
    put_by: dict[float, float] = {}
    t_years = _time_to_expiry_years(exp, today)

    def _accum(df: pd.DataFrame | None, opt_type: str, sign: float, target: dict[float, float]) -> None:
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            oi = row.get("openInterest")
            if oi is None or pd.isna(oi) or float(oi) <= 0:
                continue
            strike = float(row["strike"])
            iv = _safe_iv(row.get("impliedVolatility"))
            if iv is None:
                continue
            g = fc.black_scholes_greeks(
                spot, strike, t_years, fc.RISK_FREE_RATE, iv, opt_type
            )["gamma"]
            gex = _gex_dollars_per_1pct(g, float(oi), spot, sign=sign)
            if gex == 0:
                continue
            target[strike] = target.get(strike, 0.0) + gex

    _accum(calls, "call", 1.0, call_by)
    _accum(puts, "put", -1.0, put_by)

    net_by: dict[float, float] = {}
    for strike in set(call_by) | set(put_by):
        net_by[strike] = call_by.get(strike, 0.0) + put_by.get(strike, 0.0)
    return call_by, put_by, net_by


def _merge_strike_maps(*maps: dict[float, float]) -> dict[float, float]:
    out: dict[float, float] = {}
    for m in maps:
        for k, v in m.items():
            out[k] = out.get(k, 0.0) + v
    return out


def _strike_rows(
    call_by: dict[float, float],
    put_by: dict[float, float],
    net_by: dict[float, float],
    *,
    spot: float,
    band_pct: float = 0.12,
) -> list[dict[str, Any]]:
    """Build chart/table rows; optionally trim far OTM tails."""
    if not net_by:
        return []
    lo = spot * (1.0 - band_pct)
    hi = spot * (1.0 + band_pct)
    strikes = sorted(k for k in net_by if lo <= k <= hi)
    if len(strikes) < 5:
        strikes = sorted(net_by.keys())

    rows: list[dict[str, Any]] = []
    for strike in strikes:
        cg = call_by.get(strike, 0.0)
        pg = put_by.get(strike, 0.0)
        ng = net_by.get(strike, 0.0)
        rows.append(
            {
                "strike": round(strike, 2),
                "call_gex": round(cg, 0),
                "put_gex": round(pg, 0),
                "net_gex": round(ng, 0),
                "abs_net_gex": round(abs(ng), 0),
            }
        )
    return rows


def _gamma_flip(net_by: dict[float, float], spot: float) -> float | None:
    """Strike where cumulative net GEX (low→high) crosses zero near spot."""
    if not net_by:
        return None
    strikes = sorted(net_by.keys())
    cum = 0.0
    prev_k, prev_cum = strikes[0], 0.0
    for k in strikes:
        cum += net_by[k]
        if prev_cum == 0.0 and cum == 0.0:
            prev_k, prev_cum = k, cum
            continue
        if prev_cum * cum <= 0 and k != prev_k:
            # linear interpolate zero crossing between prev_k and k
            if cum == prev_cum:
                return float(k)
            frac = prev_cum / (prev_cum - cum)
            return float(prev_k + frac * (k - prev_k))
        prev_k, prev_cum = k, cum
    # fallback: strike closest to spot with smallest |net|
    return float(min(net_by.keys(), key=lambda x: (abs(x - spot), abs(net_by[x]))))


def _walls(
    call_by: dict[float, float],
    put_by: dict[float, float],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    call_wall = None
    if call_by:
        k = max(call_by, key=lambda x: call_by[x])
        call_wall = {"strike": k, "gex": round(call_by[k], 0)}
    put_wall = None
    if put_by:
        k = min(put_by, key=lambda x: put_by[x])
        put_wall = {"strike": k, "gex": round(put_by[k], 0)}
    return call_wall, put_wall


def _regime(net: float, gross: float) -> GexRegime:
    if gross <= 0:
        return "Neutral Gamma"
    if abs(net) / gross < REGIME_NEUTRAL_BAND:
        return "Neutral Gamma"
    return "Positive Gamma" if net > 0 else "Negative Gamma"


def _select_expirations(
    available: list[str],
    filt: ExpirationFilter,
    *,
    today: date,
    custom_date: str | None,
) -> tuple[list[str], str | None]:
    """Return expiration list to load and optional 0DTE date for breakout."""
    if not available:
        return [], None

    parsed = sorted(_parse_expiration(s) for s in available)
    upcoming = [d for d in parsed if d >= today]
    pool = upcoming if upcoming else parsed
    today_str = today.strftime("%Y-%m-%d")
    odte = today_str if today_str in available else None

    if filt == "0dte":
        if odte is None:
            raise ServiceError(
                "no_0dte",
                f"No same-day (0DTE) expiration listed for this ticker.",
            )
        return [today_str], odte

    if filt == "nearest":
        return [pool[0].strftime("%Y-%m-%d")], odte

    if filt == "custom":
        if not custom_date or not custom_date.strip():
            raise ServiceError("missing_custom_date", "Pick a custom expiration date.")
        raw = custom_date.strip()
        if raw in available:
            return [raw], odte
        if "/" in raw or re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            from services import analytics as biz

            try:
                mm, dd, year = biz.parse_expiration_input(raw)
                resolved = biz.resolve_expiration(mm, dd, available, year=year)
            except ValueError as exc:
                raise ServiceError(
                    "expiration_not_found",
                    f"No expiration matches {raw}.",
                ) from exc
            return [resolved], odte
        raise ServiceError(
            "expiration_not_found",
            f"`{raw}` is not in the listed expirations.",
        )

    # all — cap count for performance
    exps = [d.strftime("%Y-%m-%d") for d in pool[:MAX_EXPIRATIONS_ALL]]
    return exps, odte


def _resolve_spot(
    symbol: str,
    hist: pd.DataFrame,
    *,
    live_fetch: bool,
) -> tuple[float, str]:
    """Last close from cache/history; overlay Yahoo live price in market hours."""
    spot = float(hist["Close"].iloc[-1])
    source = "cache"
    if should_live_refresh(live_fetch):
        live = fetch_live_last_price(symbol)
        if live is not None and not pd.isna(live):
            spot = float(live)
            source = "live"
    return round(spot, 2), source


def get_gex_levels(
    ticker: str,
    *,
    expiration_filter: ExpirationFilter = "nearest",
    custom_date: str | None = None,
    live_fetch: bool = False,
    view: Literal["total", "0dte"] = "total",
) -> dict[str, Any]:
    """GEX ladder, walls, gamma flip, and regime for *ticker*."""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ServiceError("missing_ticker", "Enter a ticker (e.g. SPY).")

    try:
        exps = get_expirations(symbol, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("expirations_failed", str(exc)) from exc

    if not exps:
        code = "no_cached_expirations" if not live_fetch else "no_options"
        raise ServiceError(
            code,
            cache_miss_message("expirations", ticker=symbol)
            if not live_fetch
            else f"`{symbol}` has no listed options.",
        )

    today = date.today()
    exp_list, odte_date = _select_expirations(
        exps, expiration_filter, today=today, custom_date=custom_date
    )

    hist = get_underlying_history(symbol, period="5d", live_fetch=live_fetch)
    if hist is None or hist.empty:
        raise ServiceError(
            "no_spot",
            cache_miss_message("spot price", ticker=symbol)
            if not live_fetch
            else f"Could not load spot for `{symbol}`.",
        )
    spot, spot_source = _resolve_spot(symbol, hist, live_fetch=live_fetch)

    # Load chains and aggregate
    all_call: dict[float, float] = {}
    all_put: dict[float, float] = {}
    odte_call: dict[float, float] = {}
    odte_put: dict[float, float] = {}
    loaded: list[str] = []

    for exp_str in exp_list:
        calls, puts = get_option_chain(symbol, exp_str, live_fetch=live_fetch)
        if (calls is None or calls.empty) and (puts is None or puts.empty):
            continue
        exp_d = _parse_expiration(exp_str)
        c, p, _n = _chain_gex_by_strike(calls, puts, spot=spot, exp=exp_d, today=today)
        all_call = _merge_strike_maps(all_call, c)
        all_put = _merge_strike_maps(all_put, p)
        loaded.append(exp_str)
        if odte_date and exp_str == odte_date:
            odte_call = _merge_strike_maps(odte_call, c)
            odte_put = _merge_strike_maps(odte_put, p)

    if not loaded:
        raise ServiceError(
            "no_cached_chain" if not live_fetch else "empty_chain",
            cache_miss_message("option chain", ticker=symbol)
            if not live_fetch
            else f"No chain data loaded for `{symbol}`.",
        )

    net_all = _merge_strike_maps(
        all_call,
        {k: v for k, v in all_put.items()},
    )
    for k in set(all_call) | set(all_put):
        net_all[k] = all_call.get(k, 0.0) + all_put.get(k, 0.0)

    use_0dte = view == "0dte" and odte_date is not None
    if use_0dte:
        call_by, put_by = odte_call, odte_put
        net_by = {
            k: odte_call.get(k, 0.0) + odte_put.get(k, 0.0)
            for k in set(odte_call) | set(odte_put)
        }
        exp_label = f"0DTE ({odte_date})"
    else:
        call_by, put_by, net_by = all_call, all_put, net_all
        if expiration_filter == "all":
            exp_label = f"All ({len(loaded)} exp)"
        elif expiration_filter == "0dte":
            exp_label = f"0DTE ({loaded[0]})"
        elif expiration_filter == "custom":
            exp_label = loaded[0]
        else:
            exp_label = f"Nearest ({loaded[0]})"

    total_call = sum(call_by.values())
    total_put = sum(put_by.values())
    net_gex = sum(net_by.values())
    gross = sum(abs(v) for v in net_by.values())

    flip = _gamma_flip(net_by, spot)
    call_wall, put_wall = _walls(call_by, put_by)
    regime = _regime(net_gex, gross)
    rows = _strike_rows(call_by, put_by, net_by, spot=spot)

    return clean_dict(
        {
            "ticker": symbol,
            "spot": spot,
            "spot_source": spot_source,
            "expiration_filter": expiration_filter,
            "expiration_label": exp_label,
            "expirations_used": loaded,
            "view": view,
            "has_0dte": odte_date is not None,
            "odte_date": odte_date,
            "metrics": {
                "net_gex": round(net_gex, 0),
                "call_gex": round(total_call, 0),
                "put_gex": round(total_put, 0),
                "gamma_flip": round(flip, 2) if flip is not None else None,
                "regime": regime,
            },
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gamma_flip": round(flip, 2) if flip is not None else None,
            "by_strike": rows,
            "formula": "GEX ($/1% move) ≈ ± Γ × OI × 100 × S² × 0.01 (calls +, puts −)",
            "disclaimer": (
                "Model GEX from Black-Scholes gamma × open interest — illustrative only, "
                "not financial advice."
            ),
            "live_fetch": live_fetch,
            "data_source": data_source_label(live_fetch),
        }
    )

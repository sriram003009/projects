"""Contract lookup, forecasts, and what-if scenario orchestration."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

import cache as fcache
import forecasting as fc
from services import analytics as biz
from services.data_access import (
    get_contract_history,
    get_expirations,
    get_option_chain,
    get_underlying_history,
)
from services.messages import cache_miss_message
from services.serialize import clean_dict, df_to_records

MMDD_RE = re.compile(r"^\d{2}/\d{2}$")


class ServiceError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _validate_contract_request(
    ticker: str,
    option_type: str,
    expiration_mmdd: str,
    strike: float,
) -> tuple[str, str, int, int, float]:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ServiceError("missing_ticker", "Please enter a stock ticker.")
    if option_type not in ("Call", "Put"):
        raise ServiceError("invalid_option_type", "Option type must be Call or Put.")
    exp = expiration_mmdd.strip()
    if not MMDD_RE.match(exp):
        raise ServiceError("invalid_expiration", "Expiration must be in MM/DD format (e.g. 06/26).")
    mm, dd = (int(x) for x in exp.split("/"))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        raise ServiceError("invalid_expiration", "Expiration MM/DD has an invalid month or day.")
    if strike <= 0:
        raise ServiceError("invalid_strike", "Strike price must be greater than zero.")
    return ticker, option_type, mm, dd, float(strike)


def lookup_contract(
    ticker: str,
    option_type: str,
    expiration_mmdd: str,
    strike: float,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Resolve contract and return header + last-30 session history."""
    ticker, option_type, mm, dd, strike = _validate_contract_request(
        ticker, option_type, expiration_mmdd, strike
    )

    try:
        expirations = get_expirations(ticker, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("expirations_failed", f"Could not fetch options for `{ticker}`: {exc}") from exc

    if not expirations:
        code = "no_cached_expirations" if not live_fetch else "no_options"
        msg = (
            cache_miss_message("expirations", ticker=ticker)
            if not live_fetch
            else f"`{ticker}` has no listed options on Yahoo Finance."
        )
        raise ServiceError(code, msg)

    try:
        expiration_date = biz.resolve_expiration(mm, dd, expirations)
    except ValueError:
        raise ServiceError(
            "expiration_not_found",
            f"No expiration matches {expiration_mmdd} for `{ticker}`.",
            {"nearest": biz.nearest_expirations(expirations)},
        )

    try:
        calls, puts = get_option_chain(ticker, expiration_date, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("chain_failed", f"Failed to load option chain: {exc}") from exc

    chain_df = calls if option_type == "Call" else puts
    if chain_df is None or chain_df.empty:
        code = "no_cached_chain" if not live_fetch else "empty_chain"
        msg = (
            cache_miss_message(
                "option chain",
                ticker=ticker,
                detail=f"exp {expiration_date}",
            )
            if not live_fetch
            else f"Empty option chain returned for {ticker} {expiration_date}."
        )
        raise ServiceError(code, msg)

    match = chain_df[chain_df["strike"].round(4) == round(strike, 4)]
    if match.empty:
        available = sorted(chain_df["strike"].unique().tolist())
        nearest = min(available, key=lambda s: abs(s - strike)) if available else None
        raise ServiceError(
            "strike_not_found",
            f"Strike {strike:g} not found for {ticker} {option_type.lower()} exp {expiration_date}.",
            {"nearest": nearest, "nearby": [s for s in available if abs(s - strike) <= 25][:10]},
        )

    row = match.iloc[0]
    contract_symbol = row["contractSymbol"]
    last_price = float(row["lastPrice"]) if pd.notna(row.get("lastPrice")) else None
    implied_vol = float(row["impliedVolatility"]) if pd.notna(row.get("impliedVolatility")) else None
    open_interest = int(row["openInterest"]) if pd.notna(row.get("openInterest")) else None

    try:
        hist = get_contract_history(contract_symbol, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("history_failed", f"Failed to fetch contract history: {exc}") from exc

    if hist is None or hist.empty:
        code = "no_cached_history" if not live_fetch else "no_history"
        msg = (
            cache_miss_message("history", ticker=contract_symbol)
            if not live_fetch
            else "No historical price data available for this contract."
        )
        raise ServiceError(code, msg)

    hist = hist.tail(30).copy()
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    underlying = None
    try:
        underlying = get_underlying_history(ticker, period="1y", live_fetch=live_fetch)
    except Exception:
        underlying = None

    stock_close = pd.Series(index=hist.index, dtype=float)
    if underlying is not None and not underlying.empty:
        stock_close = underlying["Close"].reindex(hist.index, method="ffill")

    display = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    display.insert(0, "Date", display.index.strftime("%Y-%m-%d"))
    display["Stock Close"] = stock_close.values
    display = display[
        ["Date", "Open", "High", "Low", "Close", "Stock Close", "Volume"]
    ]

    trend = (
        biz.weekly_trend_note(ticker, underlying)
        if underlying is not None and not underlying.empty
        else None
    )

    underlying_meta = fcache.cache_metadata(ticker)
    contract_meta = fcache.cache_metadata(contract_symbol)

    spot = float(underlying["Close"].iloc[-1]) if underlying is not None and not underlying.empty else None
    today = pd.Timestamp(date.today())
    exp_ts = pd.Timestamp(expiration_date)
    T0 = fc.time_to_expiry_years(today, exp_ts) if spot is not None else None
    iv_for_model = implied_vol if implied_vol and implied_vol > 0 else None
    realized_vol = (
        fc.historical_volatility(underlying["Close"], window=30)
        if underlying is not None and not underlying.empty
        else None
    )
    sigma = iv_for_model if iv_for_model is not None else realized_vol

    return clean_dict(
        {
            "ticker": ticker,
            "option_type": option_type,
            "expiration_input": expiration_mmdd.strip(),
            "expiration_date": expiration_date,
            "strike": strike,
            "contract_symbol": contract_symbol,
            "last_price": last_price,
            "implied_vol": implied_vol,
            "open_interest": open_interest,
            "live_fetch": live_fetch,
            "data_source": "live" if live_fetch else "cache",
            "cache_badge": biz.format_cache_badge(contract_symbol, live_fetch),
            "underlying_meta": underlying_meta,
            "contract_meta": contract_meta,
            "weekly_trend": trend,
            "sessions": df_to_records(display),
            "history_raw": df_to_records(hist.reset_index().rename(columns={"index": "Date"})),
            "context": {
                "spot": spot,
                "sigma": sigma,
                "T0": T0,
                "exp_ts": exp_ts.isoformat(),
            },
        }
    )


def build_forecasts(
    ticker: str,
    option_type: str,
    expiration_mmdd: str,
    strike: float,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Run all four forecast models for a contract."""
    base = lookup_contract(ticker, option_type, expiration_mmdd, strike, live_fetch)
    ctx = base["context"]
    spot = ctx["spot"]
    sigma = ctx["sigma"]
    T0 = ctx["T0"]
    expiration_date = base["expiration_date"]

    underlying = get_underlying_history(ticker, period="1y", live_fetch=live_fetch)
    if underlying is None or underlying.empty or len(underlying) < 60:
        code = "insufficient_underlying_cache" if not live_fetch else "insufficient_underlying"
        msg = (
            cache_miss_message(
                "underlying history (~1 year)",
                ticker=ticker,
                detail="need ~60 trading days for forecasts",
            )
            if not live_fetch
            else f"Not enough underlying history for `{ticker}` (need ~60 days)."
        )
        raise ServiceError(code, msg)

    today = pd.Timestamp(date.today())
    exp_ts = pd.Timestamp(expiration_date)
    days_to_exp = max((exp_ts.normalize() - today.normalize()).days, 0)
    forecast_days = min(5, max(days_to_exp, 1))

    inp = fc.ForecastInputs(
        spot=float(spot),
        strike=float(strike),
        sigma=float(sigma),
        r=fc.RISK_FREE_RATE,
        T0_years=float(T0),
        option_type="call" if option_type == "Call" else "put",
        days=forecast_days,
    )

    mc_df = fc.forecast_monte_carlo(underlying["Close"], inp, n_paths=5000)
    patterns = fc.detect_candle_patterns(underlying)
    pattern_stats = fc.pattern_conditional_stats(underlying, patterns, horizon=forecast_days)
    pattern_fc = fc.forecast_from_patterns(underlying, inp)
    arima_df = fc.forecast_arima(underlying["Close"], inp)
    rf_df = fc.forecast_random_forest(underlying, inp)

    opt_type = "call" if option_type == "Call" else "put"
    current_opt_price = float(
        fc.black_scholes_price(spot, strike, T0, fc.RISK_FREE_RATE, sigma, opt_type)
    )

    hist = get_contract_history(base["contract_symbol"], live_fetch=live_fetch).tail(30)
    last_idx = hist.index[-1] if not hist.empty else today
    future_dates = pd.bdate_range(start=last_idx + pd.Timedelta(days=1), periods=forecast_days)
    date_strs = [d.strftime("%Y-%m-%d") for d in future_dates]

    def _attach_dates(df: pd.DataFrame | None) -> list[dict]:
        if df is None:
            return []
        d = df.copy()
        d.insert(0, "Date", date_strs[: len(d)])
        return df_to_records(d)

    summary_rows = [
        {
            "approach": "A. Monte Carlo + BS",
            "today": current_opt_price,
            "day_n_median": float(mc_df["o_p50"].iloc[-1]),
            "lower": float(mc_df["o_p10"].iloc[-1]),
            "upper": float(mc_df["o_p90"].iloc[-1]),
            "notes": "GBM, 5000 paths, BS revalued each step",
        },
    ]

    if pattern_fc is not None:
        summary_rows.append(
            {
                "approach": "B. Candlestick patterns",
                "today": current_opt_price,
                "day_n_median": float(pattern_fc["predicted_option_price"]),
                "lower": None,
                "upper": None,
                "notes": f"After {pattern_fc['pattern']} (n={pattern_fc['n']})",
            }
        )
    else:
        summary_rows.append(
            {
                "approach": "B. Candlestick patterns",
                "today": current_opt_price,
                "day_n_median": None,
                "lower": None,
                "upper": None,
                "notes": "No pattern detected on the most recent bar",
            }
        )

    if arima_df is not None:
        summary_rows.append(
            {
                "approach": "C. ARIMA(1,1,1)",
                "today": current_opt_price,
                "day_n_median": float(arima_df["o_mean"].iloc[-1]),
                "lower": float(arima_df["o_low"].iloc[-1]),
                "upper": float(arima_df["o_high"].iloc[-1]),
                "notes": "80% confidence band on log prices",
            }
        )
    else:
        summary_rows.append(
            {
                "approach": "C. ARIMA(1,1,1)",
                "today": current_opt_price,
                "day_n_median": None,
                "lower": None,
                "upper": None,
                "notes": "ARIMA fit failed",
            }
        )

    if rf_df is not None:
        summary_rows.append(
            {
                "approach": "D. Random Forest",
                "today": current_opt_price,
                "day_n_median": float(rf_df["o_predicted"].iloc[-1]),
                "lower": None,
                "upper": None,
                "notes": "Iterated forward; lag returns + RSI/MACD/ATR + candle ratios",
            }
        )
    else:
        summary_rows.append(
            {
                "approach": "D. Random Forest",
                "today": current_opt_price,
                "day_n_median": None,
                "lower": None,
                "upper": None,
                "notes": "Insufficient training data",
            }
        )

    recent_patterns = fc.latest_patterns(patterns, lookback=3)

    return clean_dict(
        {
            "contract": base,
            "metrics": {
                "spot": spot,
                "sigma": sigma,
                "sigma_pct": sigma * 100,
                "T0_days": T0 * 365.25,
                "forecast_days": forecast_days,
                "days_to_exp": days_to_exp,
                "current_option_price": current_opt_price,
            },
            "summary": summary_rows,
            "monte_carlo": _attach_dates(mc_df),
            "pattern_stats": df_to_records(pattern_stats),
            "pattern_forecast": clean_dict(pattern_fc) if pattern_fc else None,
            "recent_patterns": recent_patterns,
            "arima": _attach_dates(arima_df),
            "random_forest": _attach_dates(rf_df),
            "history_dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "history_closes": [float(v) for v in hist["Close"].tolist()],
            "forecast_dates": date_strs,
        }
    )


def build_whatif(
    ticker: str,
    option_type: str,
    expiration_mmdd: str,
    strike: float,
    target_price: float,
    target_mmdd: str,
    scenario_iv_pct: float,
    live_fetch: bool = False,
) -> dict[str, Any]:
    """Greeks panel + scenario reprice + sensitivity grid."""
    base = lookup_contract(ticker, option_type, expiration_mmdd, strike, live_fetch)
    ctx = base["context"]
    spot = float(ctx["spot"])
    sigma = float(ctx["sigma"])
    T0 = float(ctx["T0"])
    exp_ts = pd.Timestamp(base["expiration_date"])
    today = pd.Timestamp(date.today())

    if not MMDD_RE.match(target_mmdd.strip()):
        raise ServiceError("invalid_target_date", "Target date must be in MM/DD format.")

    t_mm, t_dd = (int(x) for x in target_mmdd.strip().split("/"))
    try:
        target_date = date(today.year, t_mm, t_dd)
        if target_date < today.date():
            target_date = date(today.year + 1, t_mm, t_dd)
    except ValueError as exc:
        raise ServiceError("invalid_target_date", f"Invalid target date: {target_mmdd}") from exc

    target_ts = pd.Timestamp(target_date)
    capped = False
    if target_ts > exp_ts:
        target_ts = exp_ts
        capped = True

    T_target = fc.time_to_expiry_years(target_ts, exp_ts)
    opt_type_short = "call" if option_type == "Call" else "put"
    scenario_sigma = scenario_iv_pct / 100.0

    scn = fc.scenario_price(
        spot=spot,
        strike=float(strike),
        T0_years=T0,
        T_target_years=T_target,
        r=fc.RISK_FREE_RATE,
        base_sigma=sigma,
        target_sigma=scenario_sigma,
        option_type=opt_type_short,
        target_S=float(target_price),
    )
    g = scn["greeks"]

    s_lo = max(min(spot * 0.70, target_price * 0.95), 0.01)
    s_hi = max(spot * 1.30, target_price * 1.05)
    s_grid = np.linspace(s_lo, s_hi, 121)
    prices_today = fc.black_scholes_price(
        s_grid, strike, T0, fc.RISK_FREE_RATE, scenario_sigma, opt_type_short
    )
    prices_target = fc.black_scholes_price(
        s_grid, strike, T_target, fc.RISK_FREE_RATE, scenario_sigma, opt_type_short
    )

    grid_lo = max(spot * 0.85, 0.01)
    grid_hi = spot * 1.15
    price_grid = []
    for s in np.linspace(grid_lo, grid_hi, 13):
        p0 = float(
            fc.black_scholes_price(s, strike, T0, fc.RISK_FREE_RATE, scenario_sigma, opt_type_short)
        )
        p1 = float(
            fc.black_scholes_price(
                s, strike, T_target, fc.RISK_FREE_RATE, scenario_sigma, opt_type_short
            )
        )
        price_grid.append(
            {
                "underlying": float(s),
                "today": p0,
                "target_date": p1,
                "time_decay": p1 - p0,
            }
        )

    pnl_rows = [
        {
            "component": "Delta · ΔS",
            "formula": f"{g['delta']:.4f} × {scn['dS']:+.2f}",
            "contribution": scn["delta_pnl"],
        },
        {
            "component": "½ · Gamma · ΔS²",
            "formula": f"0.5 × {g['gamma']:.4f} × ({scn['dS']:+.2f})²",
            "contribution": scn["gamma_pnl"],
        },
        {
            "component": "Theta · days",
            "formula": f"{g['theta_per_day']:.4f} × {scn['days_elapsed']:.0f}",
            "contribution": scn["theta_pnl"],
        },
        {
            "component": "Vega · Δσ",
            "formula": f"{g['vega_per_pct']:.4f} × {scn['dsigma'] * 100:+.2f}pp",
            "contribution": scn["vega_pnl"],
        },
        {
            "component": "Residual (higher-order)",
            "formula": "BS ΔP − attributed",
            "contribution": scn["residual"],
        },
    ]

    waterfall = [
        {"label": "Starting price", "value": scn["current_price"], "measure": "absolute"},
        {"label": "From stock move (Delta)", "value": scn["delta_pnl"], "measure": "relative"},
        {"label": "From curve (Gamma)", "value": scn["gamma_pnl"], "measure": "relative"},
        {"label": "From time (Theta)", "value": scn["theta_pnl"], "measure": "relative"},
        {"label": "From vol (Vega)", "value": scn["vega_pnl"], "measure": "relative"},
        {"label": "Higher-order", "value": scn["residual"], "measure": "relative"},
        {"label": "Final BS reprice", "value": scn["bs_reprice"], "measure": "total"},
    ]

    return clean_dict(
        {
            "contract": base,
            "target_price": target_price,
            "target_date": target_ts.strftime("%Y-%m-%d"),
            "target_capped": capped,
            "scenario_iv_pct": scenario_iv_pct,
            "greeks": g,
            "scenario": scn,
            "pnl_attribution": pnl_rows,
            "waterfall": waterfall,
            "sensitivity": {
                "s_grid": [float(x) for x in s_grid],
                "prices_today": [float(x) for x in np.atleast_1d(prices_today)],
                "prices_target": [float(x) for x in np.atleast_1d(prices_target)],
                "spot": spot,
                "target_price": target_price,
            },
            "price_grid": price_grid,
        }
    )


def get_put_call_analysis(
    ticker: str,
    expiration_mmdd: str,
    live_fetch: bool = False,
) -> dict[str, Any]:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ServiceError("missing_ticker", "Enter a ticker symbol.")
    if not MMDD_RE.match(expiration_mmdd.strip()):
        raise ServiceError("invalid_expiration", "Expiration must be in MM/DD format.")

    try:
        exps = get_expirations(ticker, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("expirations_failed", str(exc)) from exc

    if not exps:
        code = "no_cached_expirations" if not live_fetch else "no_options"
        msg = (
            cache_miss_message("expirations", ticker=ticker)
            if not live_fetch
            else f"`{ticker}` has no listed options on Yahoo Finance."
        )
        raise ServiceError(code, msg)

    mm, dd = (int(x) for x in expiration_mmdd.strip().split("/"))
    try:
        exp_date = biz.resolve_expiration(mm, dd, exps)
    except ValueError:
        raise ServiceError(
            "expiration_not_found",
            f"No expiration matches {expiration_mmdd} for `{ticker}`.",
            {"nearest": biz.nearest_expirations(exps)},
        )

    stats = biz.fetch_put_call_analysis(ticker, exp_date, live_fetch)
    if stats is None:
        code = "no_cached_chain" if not live_fetch else "empty_chain"
        msg = (
            cache_miss_message(
                "option chain",
                ticker=ticker,
                detail=f"exp {exp_date}",
            )
            if not live_fetch
            else f"No option chain data for `{ticker}` exp {exp_date}."
        )
        raise ServiceError(code, msg)

    calls, puts = get_option_chain(ticker, exp_date, live_fetch=live_fetch)

    def _top_strikes(df: pd.DataFrame | None) -> list[dict]:
        if df is None or df.empty or "volume" not in df.columns:
            return []
        top = (
            df[["strike", "volume", "openInterest", "lastPrice"]]
            .sort_values("volume", ascending=False)
            .head(10)
            .reset_index(drop=True)
        )
        return df_to_records(top)

    return clean_dict(
        {
            "ticker": ticker,
            "expiration_date": exp_date,
            "live_fetch": live_fetch,
            "data_source": "live" if live_fetch else "cache",
            "stats": stats,
            "top_call_strikes": _top_strikes(calls),
            "top_put_strikes": _top_strikes(puts),
        }
    )


def get_cached_contract_detail(contract_symbol: str) -> dict[str, Any]:
    parsed = biz.parse_option_symbol(contract_symbol)
    if parsed is None:
        raise ServiceError("invalid_symbol", f"Could not parse `{contract_symbol}`.")

    hist = fcache.disk_cached_history(contract_symbol, live_fetch=False)
    if hist is None or hist.empty:
        raise ServiceError("no_cache", f"No cached history for `{contract_symbol}`.")

    hist = hist.tail(30).copy()
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    ticker = parsed["ticker"]
    underlying = fcache.disk_cached_history(ticker, live_fetch=False)
    stock_close = pd.Series(index=hist.index, dtype=float)
    if underlying is not None and not underlying.empty:
        stock_close = underlying["Close"].reindex(hist.index, method="ffill")

    display = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    display.insert(0, "Date", display.index.strftime("%Y-%m-%d"))
    display["Stock Close"] = stock_close.values

    trend = (
        biz.weekly_trend_note(ticker, underlying)
        if underlying is not None and not underlying.empty
        else None
    )

    return clean_dict(
        {
            **parsed,
            "meta": fcache.cache_metadata(contract_symbol),
            "weekly_trend": trend,
            "sessions": df_to_records(
                display[["Date", "Open", "High", "Low", "Close", "Stock Close", "Volume"]]
            ),
        }
    )

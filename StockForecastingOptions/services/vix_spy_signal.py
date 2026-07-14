"""VIX term structure + z-score + SPY technicals → BUY CALL / BUY PUT / NO TRADE."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

import pandas as pd

import cache as fcache
from services.contract_service import ServiceError
from services.data_access import data_source_label, get_underlying_history
from services.messages import cache_miss_message
from services.serialize import clean_dict

Signal = Literal["BUY CALL", "BUY PUT", "NO TRADE"]
Regime = Literal["Contango", "Backwardation"]
Stress = Literal["EXTREME_HIGH", "EXTREME_LOW", "NORMAL"]
Trend = Literal["Bullish", "Bearish", "Neutral"]

SPY_SYMBOL = "SPY"
VIX_SYMBOL = "^VIX"
VIX3M_SYMBOL = "^VIX3M"

DEFAULT_THRESHOLDS: dict[str, float | int] = {
    "term_structure_backwardation": 1.0,
    "vix_zscore_extreme_high": 2.0,
    "vix_zscore_extreme_low": -1.5,
    "vix_zscore_lookback": 20,
    "rsi_bullish_min": 50.0,
    "rsi_bearish_max": 50.0,
    "vwap_lookback": 20,
    "ema_fast": 9,
    "ema_slow": 20,
    "rsi_period": 14,
    "confidence_high_min": 85,
    "confidence_medium_min": 55,
    "spy_session_down_pct": 0.5,
    "spy_session_up_pct": 0.5,
}

DISCLAIMER = (
    "Rules-based signal, not a guarantee. Thresholds are tunable starting points — "
    "backtest before trading. Not financial advice."
)


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def _merge_thresholds(overrides: dict[str, Any] | None) -> dict[str, float | int]:
    cfg = deepcopy(DEFAULT_THRESHOLDS)
    if overrides:
        for key, val in overrides.items():
            if key in cfg and val is not None:
                cfg[key] = val
    return cfg


def _rsi(close: pd.Series, period: int) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_loss = float(loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = float(gain.iloc[-1]) / last_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _rolling_vwap(df: pd.DataFrame, lookback: int) -> float | None:
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns) or len(df) < lookback:
        return None
    window = df.tail(lookback)
    vol = window["Volume"].astype(float)
    if vol.sum() <= 0:
        return None
    typical = (window["High"] + window["Low"] + window["Close"]) / 3.0
    return float((typical * vol).sum() / vol.sum())


def _vix_price_level(vix: float) -> tuple[str, str]:
    """Absolute VIX level label and short description."""
    if vix >= 30:
        return "Extreme", "Panic-level fear — big SPY swings, bounce or further drop both possible."
    if vix >= 25:
        return "High", "High fear — SPY often under pressure or very volatile."
    if vix >= 20:
        return "Elevated", "Worries picking up — SPY rallies may struggle."
    if vix >= 15:
        return "Normal", "Typical range — SPY usually follows its trend more than VIX."
    if vix >= 12:
        return "Low", "Calm market — SPY can drift up, but shocks have less cushion."
    return "Very Low", "Complacency — SPY often quiet, but a surprise can hit harder."


def _vix_spy_implication(
    *,
    vix: float,
    vix_level: str,
    stress: Stress,
    regime: Regime,
    trend: Trend,
    vix_chg_1d: float | None,
) -> str:
    """Plain English: what today's VIX reading tends to mean for SPY."""
    parts: list[str] = [
        f"VIX at {vix:.2f} is {vix_level.lower()} versus history (typical 'quiet' is ~12–15, 'scared' is ~25+)."
    ]

    if vix_chg_1d is not None:
        if vix_chg_1d >= 5:
            parts.append(
                "VIX jumped today — that often goes with SPY selling or choppy drops."
            )
        elif vix_chg_1d <= -5:
            parts.append(
                "VIX fell sharply today — that often helps SPY stabilize or bounce."
            )
        elif vix_chg_1d > 0:
            parts.append("VIX ticked up — mild headwind for SPY.")
        elif vix_chg_1d < 0:
            parts.append("VIX ticked down — mild tailwind for SPY.")

    if stress == "EXTREME_HIGH":
        parts.append(
            "Z-score says fear is unusually HIGH — watch for mean-reversion bounces in SPY, "
            "but whipsaws are common."
        )
    elif stress == "EXTREME_LOW":
        parts.append(
            "Z-score says fear is unusually LOW — SPY can keep climbing, but complacency "
            "pullbacks happen when something spooks the market."
        )

    if regime == "Backwardation":
        parts.append(
            "Term structure is backwardation (near-term fear > longer-term) — SPY often "
            "acts nervous short-term."
        )
    else:
        parts.append(
            "Term structure is contango (calmer curve) — less panic in the options market."
        )

    if trend == "Bullish":
        parts.append("SPY trend is still Bullish — price action is fighting any fear.")
    elif trend == "Bearish":
        parts.append("SPY trend is Bearish — price is already weak alongside VIX.")
    else:
        parts.append("SPY trend is unclear — wait for direction before leaning on VIX alone.")

    return " ".join(parts)


def _load_history(symbol: str, *, period: str, live_fetch: bool) -> pd.DataFrame:
    try:
        df = get_underlying_history(symbol, period=period, live_fetch=live_fetch)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(
            "history_failed",
            f"Could not load history for `{symbol}`: {exc}",
        ) from exc

    if df is None or df.empty:
        if not live_fetch:
            raise ServiceError(
                "no_cached_history",
                cache_miss_message("price history", ticker=symbol),
            )
        raise ServiceError("no_history", f"No price history available for `{symbol}`.")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ServiceError("invalid_history", f"Unexpected index type for `{symbol}`.")

    if "Close" not in df.columns:
        raise ServiceError("invalid_history", f"Close column missing for `{symbol}`.")

    return _prepare_df(df)


def _classify_regime(ratio: float, threshold: float) -> Regime:
    return "Backwardation" if ratio > threshold else "Contango"


def _classify_stress(z: float, cfg: dict[str, float | int]) -> Stress:
    if z > float(cfg["vix_zscore_extreme_high"]):
        return "EXTREME_HIGH"
    if z < float(cfg["vix_zscore_extreme_low"]):
        return "EXTREME_LOW"
    return "NORMAL"


def _classify_trend(
    price: float,
    vwap: float | None,
    ema_fast: float,
    ema_slow: float,
    rsi: float | None,
    cfg: dict[str, float | int],
) -> Trend:
    if vwap is None or rsi is None:
        return "Neutral"
    if (
        price > vwap
        and price > ema_fast > ema_slow
        and rsi > float(cfg["rsi_bullish_min"])
    ):
        return "Bullish"
    if (
        price < vwap
        and price < ema_fast < ema_slow
        and rsi < float(cfg["rsi_bearish_max"])
    ):
        return "Bearish"
    return "Neutral"


def _apply_session_trend_filter(
    structure_trend: Trend,
    spy_chg_1d_pct: float | None,
    cfg: dict[str, float | int],
) -> tuple[Trend, str | None]:
    """Downgrade structure trend when today's SPY session contradicts it."""
    if spy_chg_1d_pct is None or structure_trend == "Neutral":
        return structure_trend, None

    down_thresh = float(cfg["spy_session_down_pct"])
    up_thresh = float(cfg["spy_session_up_pct"])

    if structure_trend == "Bullish" and spy_chg_1d_pct <= -down_thresh:
        return (
            "Neutral",
            (
                f"Multi-day SPY structure is Bullish (VWAP/EMA/RSI), but today's session is "
                f"down {abs(spy_chg_1d_pct):.2f}% — cannot issue BUY CALL against a red day."
            ),
        )
    if structure_trend == "Bearish" and spy_chg_1d_pct >= up_thresh:
        return (
            "Neutral",
            (
                f"Multi-day SPY structure is Bearish (VWAP/EMA/RSI), but today's session is "
                f"up {spy_chg_1d_pct:.2f}% — cannot issue BUY PUT against a green day."
            ),
        )
    return structure_trend, None


def _combine_signal(regime: Regime, stress: Stress, trend: Trend) -> tuple[Signal, str]:
    if trend == "Neutral":
        return "NO TRADE", "Trend neutral — price/VWAP/EMA/RSI not aligned."

    if stress == "EXTREME_LOW" and trend == "Bearish":
        return "BUY PUT", "Extreme low VIX z-score + bearish trend — complacency reversal watch."

    if regime == "Contango" and stress == "NORMAL" and trend == "Bullish":
        return "BUY CALL", "Contango + normal VIX stress + bullish technical confirmation."

    if regime == "Contango" and stress == "NORMAL" and trend == "Bearish":
        return "BUY PUT", "Contango + normal VIX stress + bearish technical confirmation."

    if regime == "Backwardation" and stress == "EXTREME_HIGH" and trend == "Bullish":
        return (
            "BUY CALL",
            "Backwardation + extreme high VIX z-score + bullish trend — mean-reversion bounce.",
        )

    if regime == "Backwardation" and stress == "EXTREME_HIGH" and trend == "Bearish":
        return "NO TRADE", "Backwardation + extreme fear + bearish trend — whipsaw risk."

    return (
        "NO TRADE",
        f"No rule matched for {regime} / {stress} / {trend}.",
    )


def _no_trade_context(regime: Regime, stress: Stress, trend: Trend) -> str | None:
    """Plain English when layers disagree — especially trend vs final signal."""
    if trend == "Bullish" and regime == "Contango" and stress == "EXTREME_LOW":
        return (
            "SPY trend is Bullish (price above VWAP, EMA9 > EMA20, RSI > 50), but the rules "
            "only allow BUY CALL when VIX stress is NORMAL under Contango. EXTREME_LOW VIX "
            "is a complacency flag — it only maps to BUY PUT when SPY trend is Bearish."
        )
    if trend == "Bullish" and regime == "Contango" and stress == "EXTREME_HIGH":
        return (
            "SPY trend is Bullish, but Contango + elevated VIX z-score has no call rule. "
            "BUY CALL in backwardation requires EXTREME_HIGH fear plus bullish confirmation."
        )
    if trend == "Bullish" and stress == "NORMAL" and regime == "Backwardation":
        return (
            "SPY trend is Bullish, but term structure is Backwardation (near-term fear elevated). "
            "BUY CALL in backwardation needs EXTREME_HIGH VIX z-score for the mean-reversion row."
        )
    if trend == "Bearish" and stress == "EXTREME_LOW" and regime == "Contango":
        return (
            "VIX complacency (EXTREME_LOW) plus Bearish SPY would trigger BUY PUT, but check "
            "that all trend conditions (below VWAP, EMA9 < EMA20, RSI < 50) are fully met."
        )
    if trend == "Neutral":
        return (
            "SPY trend is Neutral — price/VWAP/EMA/RSI not aligned, or today's session "
            "contradicts the multi-day structure."
        )
    if trend == "Bullish":
        return (
            "SPY trend is Bullish on its own, but the combined VIX regime and stress level "
            f"({regime} / {stress}) does not match any BUY CALL row in the signal table."
        )
    if trend == "Bearish":
        return (
            f"SPY trend is Bearish, but {regime} / {stress} does not match any BUY PUT row "
            "in the signal table."
        )
    return None


def _layer_alignment(
    signal: Signal,
    regime: Regime,
    stress: Stress,
    trend: Trend,
) -> list[dict[str, Any]]:
    """Three layers and whether each supports the final signal."""
    target = None
    if signal == "BUY CALL":
        target = "Call"
    elif signal == "BUY PUT":
        target = "Put"

    layers: list[dict[str, Any]] = []

    # Layer 1 — term structure regime
    if target == "Call":
        regime_aligned = regime == "Contango" or (
            regime == "Backwardation" and stress == "EXTREME_HIGH"
        )
        regime_bias = "Call" if regime == "Contango" else "Put"
    elif target == "Put":
        regime_aligned = regime == "Contango" or stress == "EXTREME_LOW"
        regime_bias = "Put" if regime == "Backwardation" else "Call"
    else:
        regime_aligned = False
        regime_bias = "Neutral"

    layers.append(
        {
            "Layer": "Regime (VIX term structure)",
            "Reading": regime,
            "Bias": regime_bias,
            "Aligned": regime_aligned if target else False,
        }
    )

    # Layer 2 — VIX stress (z-score)
    if target == "Call":
        stress_aligned = stress == "NORMAL" or (
            stress == "EXTREME_HIGH" and regime == "Backwardation"
        )
        stress_bias = (
            "Call"
            if stress == "EXTREME_HIGH" and regime == "Backwardation"
            else "Neutral"
        )
    elif target == "Put":
        stress_aligned = stress == "NORMAL" or stress == "EXTREME_LOW"
        stress_bias = "Put" if stress in {"EXTREME_LOW", "EXTREME_HIGH"} else "Neutral"
    else:
        stress_aligned = False
        stress_bias = stress

    layers.append(
        {
            "Layer": "Stress (VIX z-score)",
            "Reading": stress,
            "Bias": stress_bias,
            "Aligned": stress_aligned if target else False,
        }
    )

    # Layer 3 — SPY trend
    trend_bias = {"Bullish": "Call", "Bearish": "Put", "Neutral": "Neutral"}[trend]
    if target:
        trend_aligned = (target == "Call" and trend == "Bullish") or (
            target == "Put" and trend == "Bearish"
        )
    else:
        trend_aligned = trend == "Neutral"

    layers.append(
        {
            "Layer": "Trend (VWAP / EMA / RSI)",
            "Reading": trend,
            "Bias": trend_bias,
            "Aligned": trend_aligned if target else False,
        }
    )

    return layers


def _confidence_pct(signal: Signal, layers: list[dict[str, Any]]) -> int:
    if signal == "NO TRADE":
        aligned = sum(1 for layer in layers if layer["Aligned"])
        if aligned == 0:
            return 15
        if aligned == 1:
            return 30
        return 45

    aligned = sum(1 for layer in layers if layer["Aligned"])
    if aligned >= 3:
        return 92
    if aligned == 2:
        return 68
    return 38


def _confidence_label(pct: int, cfg: dict[str, float | int]) -> str:
    if pct >= int(cfg["confidence_high_min"]):
        return "High"
    if pct >= int(cfg["confidence_medium_min"]):
        return "Medium"
    return "Low"


def _suggested_strike(
    signal: Signal,
    spy_close: float,
    confidence_pct: int,
) -> dict[str, Any] | None:
    if signal == "NO TRADE":
        return None

    is_call = signal == "BUY CALL"
    if confidence_pct >= 85:
        delta_low, delta_high = 0.48, 0.52
        strike_offset = 0
    elif confidence_pct >= 55:
        delta_low, delta_high = 0.42, 0.58
        strike_offset = -1 if is_call else 1
    else:
        delta_low, delta_high = 0.35, 0.65
        strike_offset = -2 if is_call else 2

    atm = round(spy_close)
    example_strike = atm + strike_offset

    return {
        "option_type": "Call" if is_call else "Put",
        "reference_price": round(spy_close, 2),
        "atm_strike": atm,
        "example_strike": example_strike,
        "delta_band": f"{delta_low:.2f}–{delta_high:.2f}",
        "notes": (
            f"Target ~{delta_low:.0%}–{delta_high:.0%} delta; band widens as confidence "
            f"falls ({confidence_pct}%). Example strike is illustrative — pick expiry/liquidity "
            f"to match delta."
        ),
    }


def get_vix_spy_signal(
    *,
    live_fetch: bool = False,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Directional SPY options bias from VIX term structure, z-score, and SPY trend."""
    cfg = _merge_thresholds(thresholds)
    lookback = int(cfg["vix_zscore_lookback"])

    spy_df = _load_history(SPY_SYMBOL, period="6mo", live_fetch=live_fetch)
    vix_df = _load_history(VIX_SYMBOL, period="6mo", live_fetch=live_fetch)
    vix3m_df = _load_history(VIX3M_SYMBOL, period="6mo", live_fetch=live_fetch)

    min_spy = max(int(cfg["ema_slow"]) + 5, int(cfg["vwap_lookback"]) + 5)
    if len(spy_df) < min_spy:
        raise ServiceError(
            "insufficient_spy_history",
            f"Need ~{min_spy} SPY sessions for VWAP/EMA/RSI.",
        )
    if len(vix_df) < lookback + 5:
        raise ServiceError(
            "insufficient_vix_history",
            f"Need ~{lookback + 5} VIX sessions for z-score.",
        )
    if len(vix3m_df) < 5:
        raise ServiceError(
            "insufficient_vix3m_history",
            cache_miss_message("VIX3M (^VIX3M) history", ticker=VIX3M_SYMBOL)
            if not live_fetch
            else "No VIX3M (^VIX3M) history available.",
        )

    vix_close = float(vix_df["Close"].iloc[-1])
    vix_1d = float(vix_df["Close"].iloc[-2]) if len(vix_df) >= 2 else vix_close
    vix_chg_1d = ((vix_close - vix_1d) / vix_1d * 100.0) if vix_1d else None
    vix3m_close = float(vix3m_df["Close"].iloc[-1])
    if vix3m_close <= 0:
        raise ServiceError("invalid_vix3m", "VIX3M close must be positive.")

    term_ratio = vix_close / vix3m_close
    regime = _classify_regime(term_ratio, float(cfg["term_structure_backwardation"]))

    vix_window = vix_df["Close"].tail(lookback)
    vix_mean = float(vix_window.mean())
    vix_std = float(vix_window.std(ddof=0))
    if vix_std == 0:
        vix_z = 0.0
    else:
        vix_z = (vix_close - vix_mean) / vix_std
    stress = _classify_stress(vix_z, cfg)
    vix_level, vix_level_note = _vix_price_level(vix_close)

    spy_close = float(spy_df["Close"].iloc[-1])
    spy_prev = float(spy_df["Close"].iloc[-2]) if len(spy_df) >= 2 else spy_close
    spy_chg_1d_pct = (
        ((spy_close - spy_prev) / spy_prev * 100.0) if spy_prev else None
    )
    ema_fast_s = spy_df["Close"].ewm(span=int(cfg["ema_fast"]), adjust=False).mean()
    ema_slow_s = spy_df["Close"].ewm(span=int(cfg["ema_slow"]), adjust=False).mean()
    ema_fast = float(ema_fast_s.iloc[-1])
    ema_slow = float(ema_slow_s.iloc[-1])
    vwap = _rolling_vwap(spy_df, int(cfg["vwap_lookback"]))
    rsi = _rsi(spy_df["Close"], int(cfg["rsi_period"]))
    structure_trend = _classify_trend(spy_close, vwap, ema_fast, ema_slow, rsi, cfg)
    trend, session_note = _apply_session_trend_filter(
        structure_trend, spy_chg_1d_pct, cfg
    )
    vix_spy_implication = _vix_spy_implication(
        vix=vix_close,
        vix_level=vix_level,
        stress=stress,
        regime=regime,
        trend=trend,
        vix_chg_1d=vix_chg_1d,
    )

    signal, rule_note = _combine_signal(regime, stress, trend)
    layers = _layer_alignment(signal, regime, stress, trend)
    confidence_pct = _confidence_pct(signal, layers)
    confidence_label = _confidence_label(confidence_pct, cfg)
    suggested_strike = _suggested_strike(signal, spy_close, confidence_pct)

    reasons = [rule_note]
    context_note = _no_trade_context(regime, stress, trend) if signal == "NO TRADE" else None
    if session_note:
        reasons.insert(0, session_note)
        if signal == "NO TRADE" and not context_note:
            context_note = session_note
    if context_note:
        reasons.append(context_note)
    for layer in layers:
        status = "supports" if layer["Aligned"] else "does not support"
        if signal != "NO TRADE" or not layer["Aligned"]:
            reasons.append(f"{layer['Layer']}: {layer['Reading']} — {status} signal.")

    summary = (
        f"{signal} ({confidence_pct}% / {confidence_label}) — "
        f"{regime}, VIX z={vix_z:+.2f}, trend {trend}."
    )

    meta_spy = fcache.cache_metadata(SPY_SYMBOL)
    meta_vix = fcache.cache_metadata(VIX_SYMBOL)
    meta_vix3m = fcache.cache_metadata(VIX3M_SYMBOL)

    return clean_dict(
        {
            "signal": signal,
            "confidence_pct": confidence_pct,
            "confidence_label": confidence_label,
            "summary": summary,
            "disclaimer": DISCLAIMER,
            "regime": regime,
            "stress": stress,
            "trend": trend,
            "structure_trend": structure_trend,
            "session_note": session_note,
            "rule_matched": rule_note,
            "context_note": context_note,
            "reasons": reasons,
            "layers": layers,
            "term_structure": {
                "vix_symbol": VIX_SYMBOL,
                "vix3m_symbol": VIX3M_SYMBOL,
                "vix_close": round(vix_close, 2),
                "vix3m_close": round(vix3m_close, 2),
                "ratio": round(term_ratio, 4),
                "backwardation_threshold": float(cfg["term_structure_backwardation"]),
            },
            "vix_stress": {
                "zscore": round(vix_z, 2),
                "lookback_days": lookback,
                "mean": round(vix_mean, 2),
                "std": round(vix_std, 2),
                "extreme_high_threshold": float(cfg["vix_zscore_extreme_high"]),
                "extreme_low_threshold": float(cfg["vix_zscore_extreme_low"]),
            },
            "vix_detail": {
                "symbol": VIX_SYMBOL,
                "close": round(vix_close, 2),
                "change_1d_pct": round(vix_chg_1d, 2) if vix_chg_1d is not None else None,
                "level": vix_level,
                "level_note": vix_level_note,
                "vs_20d_avg": round(vix_mean, 2),
                "spy_implication": vix_spy_implication,
            },
            "spy_technicals": {
                "symbol": SPY_SYMBOL,
                "close": round(spy_close, 2),
                "change_1d_pct": round(spy_chg_1d_pct, 2)
                if spy_chg_1d_pct is not None
                else None,
                "vwap": round(vwap, 2) if vwap is not None else None,
                "ema9": round(ema_fast, 2),
                "ema20": round(ema_slow, 2),
                "rsi14": round(rsi, 1) if rsi is not None else None,
                "above_vwap": vwap is not None and spy_close > vwap,
                "ema_stack_bull": ema_fast > ema_slow and spy_close > ema_fast,
                "ema_stack_bear": ema_fast < ema_slow and spy_close < ema_fast,
            },
            "suggested_strike": suggested_strike,
            "thresholds": cfg,
            "live_fetch": live_fetch,
            "data_source": data_source_label(live_fetch),
            "cache_meta": {
                "spy": meta_spy,
                "vix": meta_vix,
                "vix3m": meta_vix3m,
            },
        }
    )

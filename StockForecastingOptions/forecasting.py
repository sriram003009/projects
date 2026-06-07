"""Forecasting utilities for the options-lookup app.

Implements four next-5-day forecast approaches, all of which model the
underlying stock first and then revalue the option via Black-Scholes:

A. Monte Carlo + Black-Scholes (projection cone)
B. Candlestick pattern recognition + historical conditional returns
C. ARIMA forecast on the underlying close prices
D. Random Forest on engineered features (lag returns, RSI, MACD, ATR, candle ratios)

NOTHING IN THIS FILE IS FINANCIAL ADVICE.  These are statistical toys.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

# Risk-free rate proxy (US 1-yr T-bill territory). Used for Black-Scholes.
RISK_FREE_RATE = 0.045
TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Black-Scholes
# --------------------------------------------------------------------------- #
def black_scholes_price(
    S: np.ndarray | float,
    K: float,
    T: np.ndarray | float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> np.ndarray | float:
    """European Black-Scholes price. Vectorized over S and T."""
    S = np.asarray(S, dtype=float)
    T = np.asarray(T, dtype=float)

    intrinsic_call = np.maximum(S - K, 0.0)
    intrinsic_put = np.maximum(K - S, 0.0)

    safe_T = np.where(T > 0, T, 1e-12)
    sigma = max(float(sigma), 1e-6)

    d1 = (np.log(np.maximum(S, 1e-12) / K) + (r + 0.5 * sigma**2) * safe_T) / (
        sigma * np.sqrt(safe_T)
    )
    d2 = d1 - sigma * np.sqrt(safe_T)

    if option_type.lower().startswith("c"):
        price = S * norm.cdf(d1) - K * np.exp(-r * safe_T) * norm.cdf(d2)
        price = np.where(T > 0, price, intrinsic_call)
    else:
        price = K * np.exp(-r * safe_T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        price = np.where(T > 0, price, intrinsic_put)

    return float(price) if price.ndim == 0 else price


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> dict[str, float]:
    """Returns Delta, Gamma, Theta (per calendar day), Vega (per 1% vol),
    and Rho (per 1% rate) for a single point. Standard Black-Scholes.

    All Greeks are returned in trader-friendly units:
      delta:        per $1 move in S                (dimensionless)
      gamma:        per $1 move in S, per $1        (1/$)
      theta_per_day: dollars lost per calendar day  ($/day)
      vega_per_pct: dollars per +1 percentage point of vol  ($/%-vol)
      rho_per_pct:  dollars per +1 percentage point of rate ($/%-rate)
    """
    is_call = option_type.lower().startswith("c")

    if T <= 0 or sigma <= 0 or S <= 0:
        if T <= 0:
            if is_call:
                delta = 1.0 if S > K else (0.5 if S == K else 0.0)
            else:
                delta = -1.0 if S < K else (-0.5 if S == K else 0.0)
        else:
            delta = 0.0
        return {
            "delta": delta,
            "gamma": 0.0,
            "theta_per_day": 0.0,
            "vega_per_pct": 0.0,
            "rho_per_pct": 0.0,
        }

    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT

    pdf_d1 = norm.pdf(d1)

    gamma = pdf_d1 / (S * sigma * sqrtT)
    vega = S * pdf_d1 * sqrtT  # per 1.0 vol; convert to per 1% below

    if is_call:
        delta = norm.cdf(d1)
        theta_per_year = (
            -(S * pdf_d1 * sigma) / (2 * sqrtT) - r * K * np.exp(-r * T) * norm.cdf(d2)
        )
        rho_per_year = K * T * np.exp(-r * T) * norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1.0
        theta_per_year = (
            -(S * pdf_d1 * sigma) / (2 * sqrtT) + r * K * np.exp(-r * T) * norm.cdf(-d2)
        )
        rho_per_year = -K * T * np.exp(-r * T) * norm.cdf(-d2)

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta_per_day": float(theta_per_year / 365.25),
        "vega_per_pct": float(vega / 100.0),
        "rho_per_pct": float(rho_per_year / 100.0),
    }


def scenario_price(
    spot: float,
    strike: float,
    T0_years: float,
    T_target_years: float,
    r: float,
    base_sigma: float,
    target_sigma: float,
    option_type: str,
    target_S: float,
) -> dict:
    """Predict option price under a scenario and decompose the move via Greeks.

    Base   = (spot, T0_years, base_sigma)         -- "today"
    Target = (target_S, T_target_years, target_sigma)

    Returns dict with:
      current_price       — BS price at base
      greeks              — Greeks at base
      delta_pnl           — delta * (target_S - spot)
      gamma_pnl           — 0.5 * gamma * (target_S - spot)^2
      theta_pnl           — theta_per_day * days_elapsed   (typically negative)
      vega_pnl            — vega_per_pct * (target_sigma - base_sigma) * 100
      attributed          — sum of the four Greek contributions
      residual            — bs_reprice_change - attributed
                            (captures higher-order curvature, vol convexity,
                             and Delta-Gamma cross terms beyond 2nd order)
      greeks_estimate     — current_price + attributed
      bs_reprice          — BS price at target
      bs_reprice_change   — bs_reprice - current_price
      days_elapsed, dS, dsigma — scenario deltas
    """
    current_price = float(
        black_scholes_price(spot, strike, T0_years, r, base_sigma, option_type)
    )
    greeks = black_scholes_greeks(spot, strike, T0_years, r, base_sigma, option_type)

    dS = float(target_S - spot)
    days_elapsed = max((T0_years - T_target_years) * 365.25, 0.0)
    dsigma = float(target_sigma - base_sigma)

    delta_pnl = greeks["delta"] * dS
    gamma_pnl = 0.5 * greeks["gamma"] * dS * dS
    theta_pnl = greeks["theta_per_day"] * days_elapsed
    # vega_per_pct is dollars per +1 percentage point of vol, so multiply by
    # the volatility shock expressed in percentage points (dsigma * 100).
    vega_pnl = greeks["vega_per_pct"] * (dsigma * 100.0)

    attributed = delta_pnl + gamma_pnl + theta_pnl + vega_pnl
    bs_reprice = float(
        black_scholes_price(
            target_S, strike, T_target_years, r, target_sigma, option_type
        )
    )
    bs_reprice_change = bs_reprice - current_price
    residual = bs_reprice_change - attributed

    return {
        "current_price": current_price,
        "greeks": greeks,
        "delta_pnl": float(delta_pnl),
        "gamma_pnl": float(gamma_pnl),
        "theta_pnl": float(theta_pnl),
        "vega_pnl": float(vega_pnl),
        "attributed": float(attributed),
        "residual": float(residual),
        "greeks_estimate": float(current_price + attributed),
        "bs_reprice": bs_reprice,
        "bs_reprice_change": float(bs_reprice_change),
        "days_elapsed": float(days_elapsed),
        "dS": dS,
        "dsigma": dsigma,
    }


def historical_volatility(close: pd.Series, window: int = 30) -> float:
    """Annualized realized volatility from log returns."""
    log_ret = np.log(close / close.shift(1)).dropna()
    if log_ret.empty:
        return 0.3
    sample = log_ret.tail(window) if len(log_ret) > window else log_ret
    return float(sample.std(ddof=0) * np.sqrt(TRADING_DAYS))


def time_to_expiry_years(today: pd.Timestamp, expiration: pd.Timestamp) -> float:
    """Calendar-day time-to-expiry in years (Black-Scholes convention)."""
    days = max((expiration.normalize() - today.normalize()).days, 0)
    return days / 365.25


# --------------------------------------------------------------------------- #
# Shared dataclass
# --------------------------------------------------------------------------- #
@dataclass
class ForecastInputs:
    spot: float
    strike: float
    sigma: float           # annualized volatility
    r: float               # annual risk-free rate
    T0_years: float        # time to expiry from "today" in years
    option_type: str       # 'call' or 'put'
    days: int = 5          # forecast horizon in trading days


# --------------------------------------------------------------------------- #
# A. Monte Carlo + Black-Scholes
# --------------------------------------------------------------------------- #
def forecast_monte_carlo(
    underlying: pd.Series,
    inp: ForecastInputs,
    n_paths: int = 5000,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulate underlying via GBM, revalue option each day with BS.

    Returns a DataFrame indexed by day-ahead (1..days) with columns:
        u_p10, u_p50, u_p90  -- underlying percentiles
        o_p10, o_p50, o_p90  -- option price percentiles
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / TRADING_DAYS

    log_returns = np.log(underlying / underlying.shift(1)).dropna()
    mu = float(log_returns.mean()) * TRADING_DAYS  # annualized drift
    sigma = inp.sigma

    Z = rng.standard_normal((n_paths, inp.days))
    drift = (mu - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt) * Z
    cum_log = np.cumsum(drift + diffusion, axis=1)
    paths = inp.spot * np.exp(cum_log)  # shape (n_paths, days)

    days_idx = np.arange(1, inp.days + 1)
    T_future = np.maximum(inp.T0_years - days_idx * dt, 0.0)

    # Vectorized BS over paths × days
    T_grid = np.tile(T_future, (n_paths, 1))
    option_prices = black_scholes_price(
        paths, inp.strike, T_grid, inp.r, inp.sigma, inp.option_type
    )

    df = pd.DataFrame(
        {
            "day": days_idx,
            "u_p10": np.percentile(paths, 10, axis=0),
            "u_p50": np.percentile(paths, 50, axis=0),
            "u_p90": np.percentile(paths, 90, axis=0),
            "o_p10": np.percentile(option_prices, 10, axis=0),
            "o_p50": np.percentile(option_prices, 50, axis=0),
            "o_p90": np.percentile(option_prices, 90, axis=0),
        }
    )
    return df


# --------------------------------------------------------------------------- #
# B. Candlestick pattern recognition
# --------------------------------------------------------------------------- #
PATTERN_LABELS = {
    "doji": "Doji",
    "hammer": "Hammer (bullish reversal)",
    "shooting_star": "Shooting Star (bearish reversal)",
    "bullish_engulfing": "Bullish Engulfing",
    "bearish_engulfing": "Bearish Engulfing",
    "morning_star": "Morning Star (bullish)",
    "evening_star": "Evening Star (bearish)",
}


def detect_candle_patterns(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Detect a set of common candlestick patterns. Returns dict of bool Series."""
    O, H, L, C = df["Open"], df["High"], df["Low"], df["Close"]
    body = (C - O).abs()
    rng = (H - L).replace(0, np.nan)
    upper_wick = H - np.maximum(O, C)
    lower_wick = np.minimum(O, C) - L
    bullish = C > O
    bearish = O > C

    patterns: dict[str, pd.Series] = {}
    patterns["doji"] = ((body / rng) < 0.1).fillna(False)
    patterns["hammer"] = (
        (lower_wick > 2 * body) & (upper_wick < body) & (body > 0)
    ).fillna(False)
    patterns["shooting_star"] = (
        (upper_wick > 2 * body) & (lower_wick < body) & (body > 0)
    ).fillna(False)

    pO, pC = O.shift(1), C.shift(1)
    prev_bearish = pO > pC
    prev_bullish = pC > pO
    patterns["bullish_engulfing"] = (
        prev_bearish & bullish & (O <= pC) & (C >= pO)
    ).fillna(False)
    patterns["bearish_engulfing"] = (
        prev_bullish & bearish & (O >= pC) & (C <= pO)
    ).fillna(False)

    O2, C2 = O.shift(2), C.shift(2)
    small_middle = body.shift(1) < body.rolling(20).mean() * 0.5
    patterns["morning_star"] = (
        (C2 < O2) & small_middle & bullish & (C > (O2 + C2) / 2)
    ).fillna(False)
    patterns["evening_star"] = (
        (C2 > O2) & small_middle & bearish & (C < (O2 + C2) / 2)
    ).fillna(False)

    return patterns


def pattern_conditional_stats(
    df: pd.DataFrame, patterns: dict[str, pd.Series], horizon: int = 5
) -> pd.DataFrame:
    """For each pattern, compute mean N-day forward return on the underlying."""
    closes = df["Close"]
    fwd_return = closes.shift(-horizon) / closes - 1.0

    rows = []
    for name, mask in patterns.items():
        valid = mask & fwd_return.notna()
        n = int(valid.sum())
        if n == 0:
            rows.append(
                {
                    "pattern": PATTERN_LABELS.get(name, name),
                    "count": 0,
                    "mean_return_pct": np.nan,
                    "median_return_pct": np.nan,
                    "std_return_pct": np.nan,
                    "win_rate_pct": np.nan,
                }
            )
            continue
        rets = fwd_return[valid]
        rows.append(
            {
                "pattern": PATTERN_LABELS.get(name, name),
                "count": n,
                "mean_return_pct": float(rets.mean() * 100),
                "median_return_pct": float(rets.median() * 100),
                "std_return_pct": float(rets.std() * 100),
                "win_rate_pct": float((rets > 0).mean() * 100),
            }
        )
    return pd.DataFrame(rows)


def latest_patterns(patterns: dict[str, pd.Series], lookback: int = 3) -> list[str]:
    """Return human-readable labels of patterns detected in the last `lookback` rows."""
    out = []
    for name, series in patterns.items():
        if series.tail(lookback).any():
            out.append(PATTERN_LABELS.get(name, name))
    return out


def forecast_from_patterns(
    underlying: pd.DataFrame, inp: ForecastInputs
) -> Optional[dict]:
    """Translate the most recent detected pattern's historical mean forward return
    into a single-point option-price forecast at day `inp.days`.

    Returns dict with keys: pattern, n, mean_return_pct, predicted_underlying,
    predicted_option_price.  None if no recent pattern was detected.
    """
    patterns = detect_candle_patterns(underlying)
    stats = pattern_conditional_stats(underlying, patterns, horizon=inp.days)
    recent = []
    for name, series in patterns.items():
        if series.iloc[-1]:
            recent.append(name)
    if not recent:
        return None

    # Pick the pattern with the largest historical sample among today's matches
    label_to_key = {PATTERN_LABELS.get(k, k): k for k in patterns.keys()}
    candidate_rows = stats[stats["pattern"].isin([PATTERN_LABELS.get(r, r) for r in recent])]
    candidate_rows = candidate_rows[candidate_rows["count"] > 0]
    if candidate_rows.empty:
        return None

    best = candidate_rows.sort_values("count", ascending=False).iloc[0]
    mean_ret = best["mean_return_pct"] / 100
    predicted_under = inp.spot * (1 + mean_ret)

    dt = 1.0 / TRADING_DAYS
    T_end = max(inp.T0_years - inp.days * dt, 0.0)
    predicted_opt = float(
        black_scholes_price(
            predicted_under, inp.strike, T_end, inp.r, inp.sigma, inp.option_type
        )
    )

    return {
        "pattern": best["pattern"],
        "n": int(best["count"]),
        "mean_return_pct": float(best["mean_return_pct"]),
        "win_rate_pct": float(best["win_rate_pct"]),
        "predicted_underlying": float(predicted_under),
        "predicted_option_price": predicted_opt,
        "stats_table": stats,
    }


# --------------------------------------------------------------------------- #
# C. ARIMA forecast on the underlying
# --------------------------------------------------------------------------- #
def forecast_arima(
    underlying: pd.Series, inp: ForecastInputs
) -> Optional[pd.DataFrame]:
    """ARIMA(1,1,1) on log prices; returns underlying + option price forecasts."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:  # pragma: no cover
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            log_prices = np.log(underlying.dropna())
            model = ARIMA(log_prices, order=(1, 1, 1))
            fit = model.fit()
            f = fit.get_forecast(steps=inp.days)
            mean_log = f.predicted_mean.values
            ci = f.conf_int(alpha=0.2)  # 80% CI
            lower_log = ci.iloc[:, 0].values
            upper_log = ci.iloc[:, 1].values
    except Exception:
        return None

    days_idx = np.arange(1, inp.days + 1)
    dt = 1.0 / TRADING_DAYS
    T_future = np.maximum(inp.T0_years - days_idx * dt, 0.0)

    u_mean = np.exp(mean_log)
    u_low = np.exp(lower_log)
    u_high = np.exp(upper_log)

    o_mean = black_scholes_price(u_mean, inp.strike, T_future, inp.r, inp.sigma, inp.option_type)
    o_low = black_scholes_price(u_low, inp.strike, T_future, inp.r, inp.sigma, inp.option_type)
    o_high = black_scholes_price(u_high, inp.strike, T_future, inp.r, inp.sigma, inp.option_type)

    if inp.option_type.lower().startswith("p"):
        # For puts, lower underlying => higher option, so swap
        o_low, o_high = o_high, o_low

    return pd.DataFrame(
        {
            "day": days_idx,
            "u_mean": u_mean,
            "u_low": u_low,
            "u_high": u_high,
            "o_mean": o_mean,
            "o_low": o_low,
            "o_high": o_high,
        }
    )


# --------------------------------------------------------------------------- #
# D. Random Forest with engineered features
# --------------------------------------------------------------------------- #
def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    feat = pd.DataFrame(index=df.index)
    close = df["Close"]
    feat["ret_1"] = close.pct_change(1)
    feat["ret_2"] = close.pct_change(2)
    feat["ret_5"] = close.pct_change(5)
    feat["ret_10"] = close.pct_change(10)

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feat["rsi"] = 100 - 100 / (1 + rs)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    feat["macd"] = ema12 - ema26
    feat["macd_signal"] = feat["macd"].ewm(span=9, adjust=False).mean()
    feat["macd_hist"] = feat["macd"] - feat["macd_signal"]

    H, L, C = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [H - L, (H - C.shift()).abs(), (L - C.shift()).abs()], axis=1
    ).max(axis=1)
    feat["atr"] = tr.rolling(14).mean()

    O = df["Open"]
    rng = (H - L).replace(0, np.nan)
    feat["body_ratio"] = (C - O).abs() / rng
    feat["upper_wick_ratio"] = (H - np.maximum(O, C)) / rng
    feat["lower_wick_ratio"] = (np.minimum(O, C) - L) / rng

    feat["vol_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    return feat


def forecast_random_forest(
    underlying_df: pd.DataFrame, inp: ForecastInputs
) -> Optional[pd.DataFrame]:
    """Train a RandomForest on engineered features to predict next-day returns,
    then iteratively roll forward `inp.days` days."""
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:  # pragma: no cover
        return None

    feat = _build_features(underlying_df)
    target = underlying_df["Close"].pct_change().shift(-1)
    train = feat.join(target.rename("y")).dropna()

    if len(train) < 80:
        return None

    X, y = train.drop(columns="y"), train["y"]
    model = RandomForestRegressor(
        n_estimators=300, max_depth=6, min_samples_leaf=5,
        random_state=42, n_jobs=-1,
    )
    model.fit(X, y)

    df_iter = underlying_df.copy()
    forecasts_under = []

    for d in range(inp.days):
        feat_now = _build_features(df_iter).iloc[[-1]]
        if feat_now.isna().any().any():
            feat_now = feat_now.fillna(0.0)
        pred_ret = float(model.predict(feat_now)[0])
        last_close = float(df_iter["Close"].iloc[-1])
        new_close = last_close * (1 + pred_ret)
        forecasts_under.append(new_close)

        next_idx = df_iter.index[-1] + pd.tseries.offsets.BDay()
        new_row = pd.DataFrame(
            {
                "Open": [last_close],
                "High": [max(last_close, new_close)],
                "Low": [min(last_close, new_close)],
                "Close": [new_close],
                "Volume": [float(df_iter["Volume"].tail(20).mean())],
            },
            index=[next_idx],
        )
        df_iter = pd.concat([df_iter, new_row])

    days_idx = np.arange(1, inp.days + 1)
    dt = 1.0 / TRADING_DAYS
    T_future = np.maximum(inp.T0_years - days_idx * dt, 0.0)
    u_arr = np.array(forecasts_under)
    o_arr = black_scholes_price(u_arr, inp.strike, T_future, inp.r, inp.sigma, inp.option_type)

    return pd.DataFrame(
        {
            "day": days_idx,
            "u_predicted": u_arr,
            "o_predicted": o_arr,
        }
    )

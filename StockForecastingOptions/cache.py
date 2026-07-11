"""Disk-backed cache for yfinance data with a user-controlled live-fetch flag.

Caches three kinds of objects in ``./.cache/``:
  1. OHLCV history (parquet) — for tickers and option contracts
  2. Option expiration lists (JSON) — small, rarely-changing
  3. Option chain calls/puts (parquet pair) — per (ticker, expiration)

Two modes via ``live_fetch``:
  - ``live_fetch=False`` (default in app):
        Only reads from disk. **No network calls at all.** Returns whatever
        is cached, or empty/None if nothing is cached.
  - ``live_fetch=True``:
        For OHLCV: incremental — fetches only the daily delta since the
        latest cached date. Caches and returns the merged data.
        For expirations / chain: refreshes the cached snapshot.

Plus a ``cache_metadata()`` helper that returns the file mtime and last bar
date so the UI can show "Data updated: 2026-06-06 22:58 (cache)".
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Approximate calendar-day spans for the yfinance ``period`` strings we use.
# Used to detect when an existing cache is too short for a new request, so the
# incremental-delta path can fall through to a full re-bootstrap.
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 184,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
    "ytd": 365, "max": 36500,
}


# --------------------------------------------------------------------------- #
# Filename helpers
# --------------------------------------------------------------------------- #
def _safe_stem(symbol: str) -> str:
    """Filesystem-safe stem for a yfinance symbol."""
    return (
        symbol.replace("^", "_idx_")
        .replace("=", "_eq_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _safe_filename(symbol: str) -> str:
    return f"{_safe_stem(symbol)}.parquet"


def _expirations_path(ticker: str) -> Path:
    return CACHE_DIR / f"{_safe_stem(ticker)}__expirations.json"


def _chain_paths(ticker: str, expiration: str) -> tuple[Path, Path]:
    exp = expiration.replace("-", "")
    base = f"{_safe_stem(ticker)}__chain_{exp}"
    return CACHE_DIR / f"{base}_calls.parquet", CACHE_DIR / f"{base}_puts.parquet"


# --------------------------------------------------------------------------- #
# Misc helpers
# --------------------------------------------------------------------------- #
def _last_business_day() -> pd.Timestamp:
    today = pd.Timestamp(dt.date.today())
    bdays = pd.bdate_range(end=today, periods=2)
    return bdays[-1].normalize()


def _strip_tz(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Drop timezone info from a DatetimeIndex; no-op for other index types."""
    if df is None or df.empty:
        return df
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        df = df.copy()
        df.index = idx.tz_localize(None)
    return df


def _now_iso_minute() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# OHLCV history (incremental)
# --------------------------------------------------------------------------- #
def disk_cached_history(
    symbol: str,
    min_period: str = "3mo",
    live_fetch: bool = True,
) -> pd.DataFrame:
    """Get OHLCV with disk cache + optional incremental live fetch."""
    path = CACHE_DIR / _safe_filename(symbol)

    cached: pd.DataFrame | None = None
    if path.exists():
        try:
            cached = pd.read_parquet(path)
            cached = _strip_tz(cached)
        except Exception:
            cached = None

    # Cache-only mode: never touch the network.
    if not live_fetch:
        return cached if cached is not None else pd.DataFrame()

    target_date = _last_business_day()

    # If the existing cache doesn't span far enough back to satisfy
    # ``min_period``, fall through to a full re-bootstrap (otherwise the
    # incremental-delta path would happily extend forward but never grow
    # backward, leaving the cache stuck at its original short window).
    if cached is not None and not cached.empty:
        expected_days = _PERIOD_TO_DAYS.get(min_period, 92)
        # 0.85 fudge factor: yfinance often returns slightly less than the
        # nominal period (weekends, holidays, IPO date, etc.).
        required_oldest = target_date - pd.Timedelta(days=int(expected_days * 0.85))
        oldest_cached = cached.index.min().normalize()
        if oldest_cached > required_oldest:
            try:
                df = yf.Ticker(symbol).history(period=min_period)
            except Exception:
                pass
            else:
                df = _strip_tz(df)
                if df is not None and not df.empty:
                    try:
                        df.to_parquet(path)
                    except Exception:
                        pass
                    return df

    # Incremental update path
    if cached is not None and not cached.empty:
        last_date = cached.index.max().normalize()
        if last_date >= target_date:
            # Today's bar is already cached but changes intraday; also refresh
            # recent sessions so prior-day closes stay aligned with Yahoo.
            start = (target_date - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        else:
            start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            delta = yf.Ticker(symbol).history(start=start)
        except Exception:
            return cached  # network failure → keep what we had

        delta = _strip_tz(delta)
        if delta is None or delta.empty:
            # Touch the file mtime so "last update attempt" reflects now
            path.touch()
            return cached

        combined = pd.concat([cached, delta])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        try:
            combined.to_parquet(path)
        except Exception:
            pass
        return combined

    # Cold path: initial bootstrap
    try:
        df = yf.Ticker(symbol).history(period=min_period)
    except Exception:
        return pd.DataFrame()

    df = _strip_tz(df)
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df

    try:
        df.to_parquet(path)
    except Exception:
        pass
    return df


# --------------------------------------------------------------------------- #
# Option expirations
# --------------------------------------------------------------------------- #
def disk_cached_expirations(ticker: str, live_fetch: bool = True) -> list[str]:
    """List of option expiration dates ('YYYY-MM-DD'), disk-cached."""
    path = _expirations_path(ticker)

    cached: list[str] = []
    if path.exists():
        try:
            with path.open() as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                cached = list(payload.get("expirations", []))
            else:
                cached = list(payload)
        except Exception:
            cached = []

    if not live_fetch:
        return cached

    try:
        result = list(yf.Ticker(ticker).options or [])
    except Exception:
        return cached

    if result:
        try:
            with path.open("w") as f:
                json.dump(
                    {"expirations": result, "updated_at": _now_iso_minute()}, f
                )
        except Exception:
            pass
        return result
    return cached


# --------------------------------------------------------------------------- #
# Option chain (calls + puts)
# --------------------------------------------------------------------------- #
def disk_cached_option_chain(
    ticker: str, expiration: str, live_fetch: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Option chain (calls, puts) for a given expiration, disk-cached."""
    calls_path, puts_path = _chain_paths(ticker, expiration)

    cached_calls = (
        _strip_tz(pd.read_parquet(calls_path)) if calls_path.exists() else None
    )
    cached_puts = (
        _strip_tz(pd.read_parquet(puts_path)) if puts_path.exists() else None
    )

    if not live_fetch:
        return (
            cached_calls if cached_calls is not None else pd.DataFrame(),
            cached_puts if cached_puts is not None else pd.DataFrame(),
        )

    try:
        chain = yf.Ticker(ticker).option_chain(expiration)
    except Exception:
        return (
            cached_calls if cached_calls is not None else pd.DataFrame(),
            cached_puts if cached_puts is not None else pd.DataFrame(),
        )

    calls = _strip_tz(chain.calls) if chain.calls is not None else pd.DataFrame()
    puts = _strip_tz(chain.puts) if chain.puts is not None else pd.DataFrame()
    try:
        if calls is not None and not calls.empty:
            calls.to_parquet(calls_path)
        if puts is not None and not puts.empty:
            puts.to_parquet(puts_path)
    except Exception:
        pass
    return calls, puts


# --------------------------------------------------------------------------- #
# Cache metadata for the UI
# --------------------------------------------------------------------------- #
def cache_metadata(symbol: str) -> dict | None:
    """Return last-update timestamp and last-bar date for an OHLCV cache.

    Only returns metadata for **time-series** caches (DatetimeIndex). Option
    chain snapshots use a RangeIndex and are skipped here — call sites can use
    the file mtime directly if they want to surface a refresh time.
    """
    path = CACHE_DIR / _safe_filename(symbol)
    if not path.exists():
        return None
    try:
        cached = _strip_tz(pd.read_parquet(path))
    except Exception:
        return None
    if cached is None or cached.empty:
        return None
    if not isinstance(cached.index, pd.DatetimeIndex):
        return None
    last_bar = cached.index.max()
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    return {
        "symbol": symbol,
        "last_bar_date": last_bar,
        "cache_updated_at": mtime,
        "num_rows": int(len(cached)),
        "file_size_kb": round(path.stat().st_size / 1024, 1),
    }


# --------------------------------------------------------------------------- #
# Maintenance
# --------------------------------------------------------------------------- #
def clear_cache(symbol: str | None = None, *, confirm: bool = False) -> int:
    """Delete cached files. Returns number of files removed.

    Modes:
      - ``clear_cache("NVDA")``                — delete just one symbol's OHLCV file.
      - ``clear_cache(None, confirm=True)``    — wipe **every** file in ``.cache/``.

    The ``confirm=True`` keyword is **required** for the full-wipe path. This
    is a safety belt: it prevents a casual script (or smoke test) from
    importing this module and accidentally calling ``clear_cache()`` to delete
    every cached parquet/JSON file. A wipe affects option-chain snapshots,
    expirations lists, and OHLCV histories for every ticker — easy to lose
    minutes or hours of cached work.
    """
    if symbol is not None:
        n = 0
        path = CACHE_DIR / _safe_filename(symbol)
        if path.exists():
            path.unlink()
            n += 1
        return n

    if not confirm:
        raise ValueError(
            "clear_cache(): wiping the entire cache requires confirm=True. "
            "Pass `confirm=True` explicitly, or pass a single `symbol=` to "
            "delete just one file."
        )

    n = 0
    for f in CACHE_DIR.glob("*"):
        if f.is_file():
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def cache_summary() -> dict:
    """Summary of cache directory."""
    files = [f for f in CACHE_DIR.glob("*") if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "directory": str(CACHE_DIR),
        "num_files": len(files),
        "total_bytes": total_bytes,
        "total_kb": round(total_bytes / 1024, 1),
    }

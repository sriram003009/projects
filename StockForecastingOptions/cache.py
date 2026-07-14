"""Disk-backed cache for yfinance data with a user-controlled live-fetch flag.

Caches three kinds of objects in ``./.cache/``:
  1. OHLCV history (parquet) — for tickers and option contracts
  2. Option expiration lists (JSON) — small, rarely-changing
  3. Option chain calls/puts (parquet pair) — per (ticker, expiration)

Fetch policy (all tabs share this via ``disk_cached_*`` helpers):

  - ``live_fetch=False`` (default):
        Disk cache only — **no network**. Missing data → empty / cache-miss errors.

  - ``live_fetch=True``:
        **Cache-first.** Prior sessions come from disk when present; missing
        historical bars are backfilled from Yahoo. **Today's** bar (and option
        chains / expirations) hit the network **only during US market hours**
        (Mon–Fri 9:30 AM–4:00 PM Eastern); outside that window cached values are
        reused.

Plus ``cache_metadata()`` for UI badges ("Data updated: …").
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

US_EASTERN = ZoneInfo("America/New_York")

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


def _now_eastern() -> dt.datetime:
    return dt.datetime.now(US_EASTERN)


def is_us_market_hours(now: dt.datetime | None = None) -> bool:
    """True on Mon–Fri between 9:30 AM and 4:00 PM US/Eastern."""
    now = now or _now_eastern()
    if now.tzinfo is None:
        now = now.replace(tzinfo=US_EASTERN)
    else:
        now = now.astimezone(US_EASTERN)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


def should_live_refresh(live_fetch: bool, now: dt.datetime | None = None) -> bool:
    """Whether intraday / snapshot Yahoo calls are allowed right now."""
    return bool(live_fetch and is_us_market_hours(now))


def data_source_label(live_fetch: bool, now: dt.datetime | None = None) -> str:
    """Human label for API responses: cache vs cache+live."""
    if not live_fetch:
        return "cache"
    return "cache+live" if should_live_refresh(live_fetch, now) else "cache"


def _strip_tz(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Drop timezone info from a DatetimeIndex; no-op for other index types."""
    if df is None or df.empty:
        return df
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        df = df.copy()
        df.index = idx.tz_localize(None)
    return df


def normalize_daily_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame:
    """Collapse to one OHLCV row per calendar day (last bar wins)."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    out = _strip_tz(df.copy())
    if not isinstance(out.index, pd.DatetimeIndex):
        if "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
            out = out.set_index("Date")
        else:
            out.index = pd.to_datetime(out.index, errors="coerce")

    out.index = out.index.normalize()
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")]
    out.sort_index(inplace=True)
    return out


def _bootstrap_history(symbol: str, min_period: str) -> pd.DataFrame:
    """Fetch the widest OHLCV window Yahoo returns for *symbol*."""
    frames: list[pd.DataFrame] = []
    start = (dt.date.today() - dt.timedelta(days=150)).isoformat()
    for kwargs in (
        {"period": min_period},
        {"period": "max"},
        {"start": start},
    ):
        try:
            chunk = yf.Ticker(symbol).history(**kwargs)
        except Exception:
            continue
        chunk = normalize_daily_ohlcv(chunk)
        if chunk is not None and not chunk.empty:
            frames.append(chunk)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated(keep="last")]
    merged.sort_index(inplace=True)
    return merged


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
    """Get OHLCV: cache-first; backfill gaps; refresh today only in market hours."""
    path = CACHE_DIR / _safe_filename(symbol)

    cached: pd.DataFrame | None = None
    if path.exists():
        try:
            cached = pd.read_parquet(path)
            cached = _strip_tz(cached)
            if cached is not None and not cached.empty:
                cached = normalize_daily_ohlcv(cached)
        except Exception:
            cached = None

    # Cache-only mode: never touch the network.
    if not live_fetch:
        return cached if cached is not None else pd.DataFrame()

    target_date = _last_business_day()

    # Cache too short → full historical bootstrap (fills missing prior days).
    if cached is not None and not cached.empty:
        expected_days = _PERIOD_TO_DAYS.get(min_period, 92)
        required_oldest = target_date - pd.Timedelta(days=int(expected_days * 0.85))
        oldest_cached = cached.index.min().normalize()
        if oldest_cached > required_oldest:
            df = _bootstrap_history(symbol, min_period)
            if df is not None and not df.empty:
                try:
                    df.to_parquet(path)
                except Exception:
                    pass
                return df

    # Warm cache through the last business day; refresh today only in session.
    if cached is not None and not cached.empty:
        last_date = cached.index.max().normalize()

        if last_date < target_date:
            # Missing prior session(s) — backfill from day after last cached bar.
            start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        elif last_date >= target_date:
            if not should_live_refresh(live_fetch):
                return cached
            # In market hours: refresh today's bar only.
            start = target_date.strftime("%Y-%m-%d")
        else:
            return cached

        try:
            delta = yf.Ticker(symbol).history(start=start)
        except Exception:
            return cached

        delta = _strip_tz(delta)
        if delta is None or delta.empty:
            path.touch()
            return cached

        combined = normalize_daily_ohlcv(pd.concat([cached, delta]))
        try:
            combined.to_parquet(path)
        except Exception:
            pass
        return combined

    # Cold path: no cache — bootstrap full history (any time of day).
    df = _bootstrap_history(symbol, min_period)
    if df is None or df.empty:
        return pd.DataFrame()

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

    if not live_fetch or not should_live_refresh(live_fetch):
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

    if not live_fetch or not should_live_refresh(live_fetch):
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

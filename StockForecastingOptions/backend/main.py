"""FastAPI backend for the Options Lookup dashboard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Project root on path so `cache`, `forecasting`, `services` import cleanly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cache as fcache
from backend.schemas import (
    CacheClearRequest,
    ContractRequest,
    PutCallRequest,
    SmaCheckRequest,
    WhatIfRequest,
)
from services import analytics as biz
from services.contract_service import (
    ServiceError,
    build_forecasts,
    build_whatif,
    get_cached_contract_detail,
    get_put_call_analysis,
    lookup_contract,
)
from services.messages import LIVE_FETCH_HINT
from services.serialize import clean_dict, df_to_records

app = FastAPI(
    title="Options Lookup API",
    description="FastAPI backend for stock options analysis, forecasts, and scanners.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _http_error(exc: ServiceError) -> HTTPException:
    status = {
        "missing_ticker": 400,
        "invalid_expiration": 400,
        "invalid_strike": 400,
        "invalid_option_type": 400,
        "invalid_target_date": 400,
        "expiration_not_found": 404,
        "strike_not_found": 404,
        "no_cached_expirations": 404,
        "no_cached_chain": 404,
        "no_cached_history": 404,
        "insufficient_underlying_cache": 404,
        "no_options": 404,
        "empty_chain": 404,
        "no_history": 404,
        "no_cache": 404,
        "invalid_symbol": 400,
    }.get(exc.code, 400)
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/watchlist")
def watchlist_symbols() -> list[dict[str, str]]:
    return [{"symbol": s, "name": n} for s, n in biz.WATCHLIST]


def _cache_hint(live_fetch: bool, missing: list[str]) -> str | None:
    if live_fetch or not missing:
        return None
    return f"No cached data for: {', '.join(missing)}." + LIVE_FETCH_HINT


@app.get("/api/watchlist/movers")
def watchlist_movers(live_fetch: bool = Query(False)) -> dict[str, Any]:
    movers = biz.get_watchlist_movers(live_fetch=live_fetch)
    gainers = [r for r in movers if r.get("available") and r.get("pct", 0) > 0]
    losers = [r for r in movers if r.get("available") and r.get("pct", 0) < 0]
    flat = [r for r in movers if r.get("available") and r.get("pct", 0) == 0]
    gainers.sort(key=lambda r: r["pct"], reverse=True)
    losers.sort(key=lambda r: r["pct"])

    def _serialize_row(r: dict) -> dict:
        out = {k: v for k, v in r.items() if k != "trend"}
        if hasattr(out.get("last_bar"), "isoformat"):
            out["last_bar"] = out["last_bar"].isoformat()
        out["trend"] = clean_dict(r.get("trend")) if r.get("trend") else None
        return clean_dict(out)

    unavailable = [r["symbol"] for r in movers if not r.get("available")]

    return {
        "live_fetch": live_fetch,
        "data_source": "live" if live_fetch else "cache",
        "cache_hint": _cache_hint(live_fetch, unavailable),
        "gainers": [_serialize_row(r) for r in gainers],
        "losers": [_serialize_row(r) for r in losers],
        "flat": [_serialize_row(r) for r in flat],
        "gainers_table": df_to_records(biz._build_movers_table(gainers, "up")),
        "losers_table": df_to_records(biz._build_movers_table(losers, "down")),
        "unavailable": unavailable,
    }


@app.get("/api/watchlist/summary")
def watchlist_summary(live_fetch: bool = Query(False)) -> dict[str, Any]:
    df = biz.get_sma_summary_table(live_fetch=live_fetch)
    display = df.drop(columns=["Name", "_above_50", "_above_200"], errors="ignore")
    missing = [
        str(r["Stock"])
        for _, r in df.iterrows()
        if "Not enough history" in str(r.get("Overall Trend", ""))
    ]
    return {
        "live_fetch": live_fetch,
        "data_source": "live" if live_fetch else "cache",
        "cache_hint": _cache_hint(live_fetch, missing),
        "rows": df_to_records(display),
        "raw": df_to_records(df),
    }


@app.post("/api/sma/check")
def sma_check(body: SmaCheckRequest) -> dict[str, Any]:
    tickers = tuple(biz._parse_ticker_list(body.tickers))
    if not tickers:
        raise HTTPException(status_code=400, detail="Enter at least one ticker.")
    check_df = biz.lookup_sma_check(tickers, live_fetch=body.live_fetch)
    vertical = biz.check_sma_vertical_table(check_df)
    weekly = [
        {"stock": r["Stock"], "text": r.get("Weekly trend", "—")}
        for _, r in check_df.iterrows()
    ]
    display = check_df.drop(columns=["_above_50", "_above_200"], errors="ignore")
    missing = [
        str(r["Stock"])
        for _, r in check_df.iterrows()
        if "No data on disk" in str(r.get("Overall Trend", ""))
            or "No cached data" in str(r.get("Overall Trend", ""))
    ]
    return {
        "live_fetch": body.live_fetch,
        "data_source": "live" if body.live_fetch else "cache",
        "cache_hint": _cache_hint(body.live_fetch, missing),
        "rows": df_to_records(display),
        "vertical": df_to_records(vertical),
        "weekly_trends": weekly,
    }


@app.post("/api/put-call/analyze")
def put_call_analyze(body: PutCallRequest) -> dict[str, Any]:
    try:
        return get_put_call_analysis(body.ticker, body.expiration_mmdd, body.live_fetch)
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/api/contract/lookup")
def contract_lookup(body: ContractRequest) -> dict[str, Any]:
    try:
        return lookup_contract(
            body.ticker,
            body.option_type,
            body.expiration_mmdd,
            body.strike,
            body.live_fetch,
        )
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/api/contract/forecasts")
def contract_forecasts(body: ContractRequest) -> dict[str, Any]:
    try:
        return build_forecasts(
            body.ticker,
            body.option_type,
            body.expiration_mmdd,
            body.strike,
            body.live_fetch,
        )
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/api/contract/what-if")
def contract_whatif(body: WhatIfRequest) -> dict[str, Any]:
    try:
        return build_whatif(
            body.ticker,
            body.option_type,
            body.expiration_mmdd,
            body.strike,
            body.target_price,
            body.target_mmdd,
            body.scenario_iv_pct,
            body.live_fetch,
        )
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.get("/api/cache/summary")
def cache_summary() -> dict[str, Any]:
    return fcache.cache_summary()


@app.get("/api/cache/contracts")
def cache_contracts() -> list[dict[str, Any]]:
    rows = biz.list_cached_contracts()
    for r in rows:
        for k in ("last_bar_date", "cache_updated_at"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return clean_dict(rows)


@app.get("/api/cache/contracts/{contract_symbol}")
def cache_contract_history(contract_symbol: str) -> dict[str, Any]:
    try:
        return get_cached_contract_detail(contract_symbol.upper())
    except ServiceError as exc:
        raise _http_error(exc) from exc


@app.post("/api/cache/clear")
def cache_clear(body: CacheClearRequest) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to wipe cache.",
        )
    n = fcache.clear_cache(body.symbol, confirm=True)
    return {"cleared": n, "symbol": body.symbol}

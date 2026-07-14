"""Pydantic request/response models for the Options Lookup API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LiveFetchQuery(BaseModel):
    live_fetch: bool = False


class ContractRequest(BaseModel):
    ticker: str
    option_type: Literal["Call", "Put"] = "Call"
    expiration_mmdd: str = Field(
        ...,
        description="MM/DD, MM/DD/YYYY (e.g. 06/26/2028), or YYYY-MM-DD",
    )
    strike: float = Field(..., gt=0)
    live_fetch: bool = False


class WhatIfRequest(ContractRequest):
    target_price: float = Field(..., gt=0)
    target_mmdd: str
    scenario_iv_pct: float = Field(..., ge=1, le=200)


class PutCallRequest(BaseModel):
    ticker: str = "SPY"
    expiration_mmdd: str
    live_fetch: bool = False


class SmaCheckRequest(BaseModel):
    tickers: str = Field(..., description="Comma or space separated symbols")
    live_fetch: bool = False


class TomorrowWatchlistAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1, description="Stock ticker to watch tomorrow")


class OptionsTrackerAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    option_type: Literal["Call", "Put"] = "Call"
    expiration_mmdd: str = Field(
        ...,
        description="MM/DD, MM/DD/YYYY (e.g. 06/26/2028), or YYYY-MM-DD",
    )
    strike: float = Field(..., gt=0)
    entry_price: float | None = Field(
        default=None,
        gt=0,
        description="Optional; defaults to last price when added",
    )
    live_fetch: bool = False


class WeekdaySessionsRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    weekday: str = Field(
        ...,
        description="Monday, Tuesday, Wednesday, Thursday, or Friday",
    )
    sessions: int = Field(20, ge=1, le=52)
    live_fetch: bool = False


class RecentSessionsRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    sessions: int = Field(20, ge=1, le=60)
    live_fetch: bool = False


class PivotLevelsRequest(BaseModel):
    ticker: str = Field("^GSPC", min_length=1, description="^GSPC (SPX), SPY, etc.")
    live_fetch: bool = False


class VixSpySignalRequest(BaseModel):
    live_fetch: bool = False
    thresholds: dict[str, float | int] | None = Field(
        default=None,
        description=(
            "Optional overrides: term_structure_backwardation, vix_zscore_extreme_high, "
            "vix_zscore_extreme_low, vix_zscore_lookback, rsi_bullish_min, rsi_bearish_max, "
            "vwap_lookback, ema_fast, ema_slow"
        ),
    )


class GexRequest(BaseModel):
    ticker: str = Field("SPY", min_length=1)
    expiration_filter: Literal["all", "0dte", "nearest", "custom"] = "nearest"
    custom_date: str | None = Field(
        default=None,
        description="YYYY-MM-DD or MM/DD when expiration_filter=custom",
    )
    view: Literal["total", "0dte"] = "total"
    live_fetch: bool = False


class CacheClearRequest(BaseModel):
    confirm: bool = False
    symbol: str | None = None


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

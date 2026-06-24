"""Thin wrappers around disk cache — no Streamlit dependency."""

from __future__ import annotations

from typing import List

import pandas as pd

import cache as fcache


def get_expirations(ticker: str, live_fetch: bool = False) -> List[str]:
    return fcache.disk_cached_expirations(ticker, live_fetch=live_fetch)


def get_option_chain(
    ticker: str, expiration: str, live_fetch: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return fcache.disk_cached_option_chain(ticker, expiration, live_fetch=live_fetch)


def get_contract_history(
    contract_symbol: str, live_fetch: bool = False
) -> pd.DataFrame:
    return fcache.disk_cached_history(
        contract_symbol, min_period="3mo", live_fetch=live_fetch
    )


def get_underlying_history(
    ticker: str, period: str = "1y", live_fetch: bool = False
) -> pd.DataFrame:
    return fcache.disk_cached_history(ticker, min_period=period, live_fetch=live_fetch)

"""JSON serialization helpers for pandas / numpy objects."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def _scalar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return v
    if pd.isna(v):
        return None
    return v


def df_to_records(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return []
    out = df.copy()
    if "Date" in out.columns:
        # Caller already added Date — drop DatetimeIndex without duplicating the column
        if isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index(drop=True)
    elif isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()
        if out.columns[0] != "Date":
            out = out.rename(columns={out.columns[0]: "Date"})
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    records: list[dict] = []
    for row in out.to_dict(orient="records"):
        records.append({k: _scalar(v) for k, v in row.items()})
    return records


def series_to_records(index: pd.Index, *columns: pd.Series) -> list[dict]:
    records: list[dict] = []
    for i in range(len(index)):
        row: dict[str, Any] = {"date": _scalar(index[i])}
        for j, col in enumerate(columns):
            name = col.name if col.name else f"col_{j}"
            row[str(name)] = _scalar(col.iloc[i])
        records.append(row)
    return records


def clean_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: clean_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_dict(v) for v in obj]
    return _scalar(obj)

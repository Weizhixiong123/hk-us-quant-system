from __future__ import annotations

import pandas as pd

_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample_ohlcv(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule not in {"W", "ME"}:
        raise ValueError(f"unsupported rule: {rule}")
    out = daily.resample(rule).agg(_AGG)
    out = out.dropna(subset=["close"])
    return out[["open", "high", "low", "close", "volume"]]

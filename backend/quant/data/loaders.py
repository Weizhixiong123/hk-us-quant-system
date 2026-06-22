from __future__ import annotations

from typing import Callable

import pandas as pd

Fetcher = Callable[[str, str, str, str], pd.DataFrame]

_COLUMN_ALIASES = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close", "Adj Close": "close",
    "Volume": "volume",
}
_REQUIRED = ["open", "high", "low", "close", "volume"]


def _default_fetcher(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    if market == "US":
        import yfinance as yf

        return yf.download(symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
    if market == "HK":
        import akshare as ak

        # akshare 港股日线，需将日期列设为索引；symbol 形如 "00700"
        code = symbol.replace(".HK", "").zfill(5)
        raw = ak.stock_hk_daily(symbol=code, adjust="")
        raw = raw.rename(columns={"date": "Date"}).set_index("Date")
        raw.index = pd.to_datetime(raw.index)
        return raw.loc[start:end]
    raise ValueError(f"unknown market: {market}")


def load_daily(
    symbol: str,
    market: str,
    start: str,
    end: str,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    fetch = fetcher or _default_fetcher
    raw = fetch(symbol, market, start, end)
    df = raw.rename(columns=_COLUMN_ALIASES)
    # 防御性去重：任意来源若产生重复列名（如 Close+Adj Close 都映射为 close），保留第一列
    df = df.loc[:, ~df.columns.duplicated()]
    df = df[[c for c in _REQUIRED if c in df.columns]].copy()
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns from data source: {missing}")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.dropna(subset=["close"])
    return df

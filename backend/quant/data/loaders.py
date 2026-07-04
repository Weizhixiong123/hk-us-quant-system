from __future__ import annotations

from typing import Callable

import pandas as pd

from quant.live.config import load_futu_config

Fetcher = Callable[[str, str, str, str], pd.DataFrame]
MinuteFetcher = Callable[[str, str, str, str, str], pd.DataFrame]

_COLUMN_ALIASES = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close", "Adj Close": "close",
    "Volume": "volume",
}
_REQUIRED = ["open", "high", "low", "close", "volume"]
_FUTU_INTERVALS = {
    "1m": "K_1M",
    "2m": "K_1M",
    "5m": "K_5M",
    "15m": "K_15M",
    "30m": "K_30M",
    "60m": "K_60M",
}


def _log_data_loader(message: str) -> None:
    print(f"[DATA] {message}", flush=True)


def _default_fetcher(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    if market == "US":
        import yfinance as yf

        return yf.download(symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=True, multi_level_index=False)
    if market == "HK":
        import akshare as ak

        # akshare 港股日线，需将日期列设为索引；symbol 形如 "00700"
        code = symbol.replace(".HK", "").zfill(5)
        raw = ak.stock_hk_daily(symbol=code, adjust="")
        raw = raw.rename(columns={"date": "Date"}).set_index("Date")
        raw.index = pd.to_datetime(raw.index)
        return raw.loc[start:end]
    raise ValueError(f"unknown market: {market}")


def _default_minute_fetcher(symbol: str, market: str, start: str, end: str, interval: str) -> pd.DataFrame:
    return _fetch_futu_minutes(symbol, market, start, end, interval)


def _fetch_futu_minutes(symbol: str, market: str, start: str, end: str, interval: str) -> pd.DataFrame:
    try:
        from futu import AuType, KLType, OpenQuoteContext, RET_OK
    except ImportError as exc:
        raise RuntimeError("未安装 futu-api，无法使用富途分钟线数据源。请先执行 pip install futu-api。") from exc

    config = load_futu_config()
    code = _to_futu_code(symbol, market)
    ktype = _to_futu_ktype(interval, KLType)
    _log_data_loader(
        f"富途分钟线开始 code={code} original_symbol={symbol} market={market} "
        f"interval={interval} range={start}~{end} host={config.host}:{config.port}"
    )
    quote_ctx = OpenQuoteContext(host=config.host, port=config.port)
    try:
        frames: list[pd.DataFrame] = []
        page_req_key = None
        page_count = 0
        while True:
            ret, data, page_req_key = quote_ctx.request_history_kline(
                code,
                start=start,
                end=end,
                ktype=ktype,
                autype=AuType.QFQ,
                page_req_key=page_req_key,
            )
            if ret != RET_OK:
                _log_data_loader(f"富途分钟线失败 code={code} error={data}")
                raise RuntimeError(f"富途分钟线下载失败 {code}: {data}")
            frames.append(data)
            page_count += 1
            _log_data_loader(f"富途分钟线分页完成 code={code} page={page_count} rows={len(data)}")
            if page_req_key is None:
                break
        if not frames:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        raw = pd.concat(frames, ignore_index=True)
    finally:
        quote_ctx.close()

    if raw.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = raw.rename(
        columns={
            "time_key": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if interval == "2m":
        df = _resample_futu_minutes(df, "2min")
    _log_data_loader(f"富途分钟线完成 code={code} rows={len(df)} pages={page_count}")
    return df


def _to_futu_code(symbol: str, market: str) -> str:
    market = market.upper()
    normalized = symbol.strip().upper()
    if normalized.startswith(("HK.", "US.")):
        return normalized
    if market == "HK":
        code = normalized.removesuffix(".HK").zfill(5)
        return f"HK.{code}"
    if market == "US":
        code = normalized.removesuffix(".US")
        return f"US.{code}"
    raise ValueError(f"unknown market: {market}")


def _to_futu_ktype(interval: str, kl_type: object) -> object:
    name = _FUTU_INTERVALS[interval]
    return getattr(kl_type, name)


def _resample_futu_minutes(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        df.resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def load_daily(
    symbol: str,
    market: str,
    start: str,
    end: str,
    fetcher: Fetcher | None = None,
) -> pd.DataFrame:
    fetch = fetcher or _default_fetcher
    raw = fetch(symbol, market, start, end)
    return _normalize_ohlcv(raw)


def load_minutes(
    symbol: str,
    market: str,
    start: str,
    end: str,
    interval: str = "5m",
    fetcher: MinuteFetcher | None = None,
) -> pd.DataFrame:
    if interval not in {"1m", "2m", "5m", "15m", "30m", "60m"}:
        raise ValueError(f"unsupported minute interval: {interval}")
    fetch = fetcher or _default_minute_fetcher
    raw = fetch(symbol, market, start, end, interval)
    return _normalize_ohlcv(raw)


def _normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=_REQUIRED)
    # 防御：若数据源返回 MultiIndex 列（如 yfinance ≥0.2.51 单标的），拍平为第 0 级
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=_COLUMN_ALIASES)
    # 防御性去重：任意来源若产生重复列名（如 Close+Adj Close 都映射为 close），保留第一列
    df = df.loc[:, ~df.columns.duplicated()]
    df = df[[c for c in _REQUIRED if c in df.columns]].copy()
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns from data source: {missing}")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    return df

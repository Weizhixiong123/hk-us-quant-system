from __future__ import annotations

import time
from collections import deque
from datetime import date, datetime
from threading import Lock
from typing import Callable

import pandas as pd

from quant.live.config import load_futu_config
from quant.live.history_quota import unpack_history_kline_quota

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
_HISTORY_QUOTA_WINDOW_DAYS = 7
_HISTORY_QUOTA_RESERVE_RATIO = 0.20


class _SlidingWindowRateLimiter:
    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            while True:
                now = self.clock()
                while self._calls and now - self._calls[0] >= self.window_seconds:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                self.sleeper(max(self.window_seconds - (now - self._calls[0]) + 0.05, 0.05))

    def cooldown(self) -> None:
        with self._lock:
            self.sleeper(self.window_seconds + 0.05)
            self._calls.clear()


_FUTU_HISTORY_LIMITER = _SlidingWindowRateLimiter(60, 30.0)


class _FutuHistoryQuotaGuard:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = Lock()
        self._clock = clock
        self._checked_at: float | None = None
        self._remaining = 0
        self._reserve = 0
        self._daily_limit = 0
        self._used_today = 0
        self._used_symbols: set[str] = set()
        self._budget_day: date | None = None

    def allow(self, quote_ctx: object, code: str, ret_ok: int) -> bool:
        normalized = code.strip().upper()
        with self._lock:
            now = self._clock()
            if self._checked_at is None or now - self._checked_at >= 30.0:
                ret, data = quote_ctx.get_history_kl_quota(get_detail=True)  # type: ignore[attr-defined]
                if ret != ret_ok:
                    raise RuntimeError(f"富途历史K线额度查询失败：{data}")
                used, self._remaining, details = unpack_history_kline_quota(data)
                total = used + self._remaining
                self._reserve = int(total * _HISTORY_QUOTA_RESERVE_RATIO)
                today = date.today()
                if self._budget_day != today:
                    auto_capacity = max(self._remaining - self._reserve, 0)
                    self._daily_limit = (
                        max(auto_capacity // _HISTORY_QUOTA_WINDOW_DAYS, 1)
                        if auto_capacity > 0
                        else 0
                    )
                    self._budget_day = today
                self._used_symbols = {
                    str(item.get("code", "")).upper()
                    for item in details
                    if item.get("code")
                }
                self._used_today = sum(
                    1 for item in details if _quota_request_date(item.get("request_time")) == today
                )
                self._checked_at = now

            if normalized in self._used_symbols:
                return True
            if self._remaining <= self._reserve or self._used_today >= self._daily_limit:
                return False
            self._remaining -= 1
            self._used_today += 1
            self._used_symbols.add(normalized)
            return True


_FUTU_HISTORY_QUOTA_GUARD = _FutuHistoryQuotaGuard()


def _log_data_loader(message: str) -> None:
    print(f"[DATA] {message}", flush=True)


def _default_fetcher(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    """默认日线数据源：富途历史日线（前复权），与分钟线共用同一数据源。"""
    return _fetch_futu_kline(symbol, market, start, end, "K_DAY")


def _free_source_fetcher(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    """免费源日线（美股 yfinance / 港股 akshare），保留作为可注入的备用数据源。"""
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
    ktype_name = _FUTU_INTERVALS[interval]
    resample_rule = "2min" if interval == "2m" else None
    return _fetch_futu_kline(symbol, market, start, end, ktype_name, resample_rule)


def _fetch_futu_kline(
    symbol: str,
    market: str,
    start: str,
    end: str,
    ktype_name: str,
    resample_rule: str | None = None,
) -> pd.DataFrame:
    """通用富途历史K线拉取，供日线（K_DAY）与分钟线（K_1M/K_5M…）共用。"""
    try:
        from futu import AuType, KLType, OpenQuoteContext, RET_OK
    except ImportError as exc:
        raise RuntimeError("未安装 futu-api，无法使用富途行情数据源。请先执行 pip install futu-api。") from exc

    config = load_futu_config()
    code = _to_futu_code(symbol, market)
    ktype = getattr(KLType, ktype_name)
    _log_data_loader(
        f"富途K线开始 code={code} original_symbol={symbol} market={market} "
        f"ktype={ktype_name} range={start}~{end} host={config.host}:{config.port}"
    )
    quote_ctx = OpenQuoteContext(host=config.host, port=config.port)
    try:
        if not _FUTU_HISTORY_QUOTA_GUARD.allow(quote_ctx, code, RET_OK):
            raise RuntimeError(f"富途历史K线预算保护：跳过新增股票 {code}")
        frames: list[pd.DataFrame] = []
        page_req_key = None
        page_count = 0
        while True:
            for attempt in range(3):
                _FUTU_HISTORY_LIMITER.wait()
                ret, data, next_page_req_key = quote_ctx.request_history_kline(
                    code,
                    start=start,
                    end=end,
                    ktype=ktype,
                    autype=AuType.QFQ,
                    page_req_key=page_req_key,
                )
                if ret == RET_OK or not _is_history_rate_limit_error(data) or attempt == 2:
                    break
                _log_data_loader(f"富途K线触发限频，等待30秒后重试 code={code} attempt={attempt + 1}/3")
                _FUTU_HISTORY_LIMITER.cooldown()
            if ret != RET_OK:
                _log_data_loader(f"富途K线失败 code={code} error={data}")
                raise RuntimeError(f"富途K线下载失败 {code}: {data}")
            page_req_key = next_page_req_key
            frames.append(data)
            page_count += 1
            _log_data_loader(f"富途K线分页完成 code={code} page={page_count} rows={len(data)}")
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
    if resample_rule:
        df = _resample_futu_minutes(df, resample_rule)
    _log_data_loader(f"富途K线完成 code={code} rows={len(df)} pages={page_count}")
    return df


def _is_history_rate_limit_error(error: object) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("频率", "每30秒最多60次", "frequency", "rate limit"))


def _quota_request_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


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

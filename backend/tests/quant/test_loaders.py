import pandas as pd
from quant.data.loaders import (
    _FutuHistoryQuotaGuard,
    _SlidingWindowRateLimiter,
    _is_history_rate_limit_error,
    _to_futu_code,
    load_daily,
    load_minutes,
)


def test_history_rate_limiter_waits_after_window_is_full():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = _SlidingWindowRateLimiter(2, 10.0, clock=lambda: now[0], sleeper=sleep)
    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert sleeps == [10.05]


def test_history_rate_limit_error_detection():
    assert _is_history_rate_limit_error("获取历史K线频率太高，请求失败，每30秒最多60次")
    assert not _is_history_rate_limit_error("股票代码不存在")


def test_history_quota_guard_reuses_existing_symbol_when_remaining_is_zero():
    class QuoteContext:
        def get_history_kl_quota(self, get_detail):
            return 0, (
                100,
                0,
                [{"code": "US.AAPL", "request_time": "2026-07-17 09:30:00"}],
            )

    guard = _FutuHistoryQuotaGuard()

    assert guard.allow(QuoteContext(), "US.AAPL", 0) is True
    assert guard.allow(QuoteContext(), "US.MSFT", 0) is False


def test_history_quota_guard_limits_new_symbols_to_daily_average():
    class QuoteContext:
        def get_history_kl_quota(self, get_detail):
            return 0, {"used_quota": 0, "remain_quota": 100, "detail_list": []}

    guard = _FutuHistoryQuotaGuard()
    allowed = [guard.allow(QuoteContext(), f"US.AUTO{i}", 0) for i in range(12)]

    assert allowed == [True] * 11 + [False]


def test_history_quota_guard_reduces_daily_budget_with_remaining_balance():
    class QuoteContext:
        def get_history_kl_quota(self, get_detail):
            return 0, (50, 50, [])

    guard = _FutuHistoryQuotaGuard()
    allowed = [guard.allow(QuoteContext(), f"US.AUTO{i}", 0) for i in range(6)]

    assert allowed == [True] * 4 + [False] * 2


def test_history_quota_guard_queries_on_first_call_when_clock_starts_at_zero():
    calls = []

    class QuoteContext:
        def get_history_kl_quota(self, get_detail):
            calls.append(get_detail)
            return 0, {"used_quota": 0, "remain_quota": 100, "detail_list": []}

    guard = _FutuHistoryQuotaGuard(clock=lambda: 0.0)

    assert guard.allow(QuoteContext(), "US.AAPL", 0) is True
    assert calls == [True]


def _stub_fetch(symbol, market, start, end):
    # 故意用乱序索引 + 别名列 + 一行缺失,验证标准化与清洗
    idx = pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0],
            "High": [10.5, 9.5, 11.5],
            "Low": [9.8, 8.8, 10.8],
            "Close": [10.2, 9.2, float("nan")],
            "Volume": [1000, 900, 1100],
        },
        index=idx,
    )


def test_load_daily_normalizes_and_sorts():
    df = load_daily("AAPL", "US", "2024-01-01", "2024-01-31", fetcher=_stub_fetch)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    # 升序
    assert df.index.is_monotonic_increasing
    # 含 NaN 的收盘行被剔除
    assert len(df) == 2
    assert df.iloc[0]["close"] == 9.2


def test_load_daily_passes_args_to_fetcher():
    captured = {}

    def fetcher(symbol, market, start, end):
        captured.update(symbol=symbol, market=market, start=start, end=end)
        return _stub_fetch(symbol, market, start, end)

    load_daily("0700.HK", "HK", "2024-01-01", "2024-02-01", fetcher=fetcher)
    assert captured == {
        "symbol": "0700.HK",
        "market": "HK",
        "start": "2024-01-01",
        "end": "2024-02-01",
    }


def _stub_fetch_with_adj_close(symbol, market, start, end):
    """模拟 yfinance auto_adjust=False 时同时返回 Close 和 Adj Close 两列的场景"""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0],
            "High": [10.5, 9.5, 11.5],
            "Low": [9.8, 8.8, 10.8],
            "Close": [10.2, 9.2, 11.2],
            "Adj Close": [10.0, 9.0, 11.0],
            "Volume": [1000, 900, 1100],
        },
        index=idx,
    )


def test_load_daily_deduplicates_close_column():
    """回归测试: 同时含 Close 与 Adj Close 的原始数据不应崩溃,
    且结果中 close 列恰好只有一列,列集合等于标准五列。"""
    df = load_daily("AAPL", "US", "2024-01-01", "2024-01-31", fetcher=_stub_fetch_with_adj_close)
    # 结果只有一个 close 列
    assert list(df.columns).count("close") == 1
    # 列集合等于标准五列
    assert set(df.columns) == {"open", "high", "low", "close", "volume"}
    # 顺序也正确
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


# ── 新增回归测试 A: MultiIndex 列拍平 ──────────────────────────────────────


def _stub_fetch_multiindex(symbol, market, start, end):
    """模拟现代 yfinance(≥0.2.51)单标的也返回二级 MultiIndex 列的场景"""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    cols = pd.MultiIndex.from_tuples(
        [("Open", "AAPL"), ("High", "AAPL"), ("Low", "AAPL"), ("Close", "AAPL"), ("Volume", "AAPL")]
    )
    data = [
        [10.0, 10.5, 9.8, 10.2, 1000],
        [9.0, 9.5, 8.8, 9.2, 900],
        [11.0, 11.5, 10.8, 11.2, 1100],
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def test_load_daily_flattens_multiindex_columns():
    """回归测试 A: yfinance MultiIndex 列应被拍平并正确重命名为标准五列,不抛异常。"""
    df = load_daily("AAPL", "US", "2024-01-01", "2024-01-31", fetcher=_stub_fetch_multiindex)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3


# ── 新增回归测试 B: volume 为 NaN 的行被剔除 ──────────────────────────────


def _stub_fetch_volume_nan(symbol, market, start, end):
    """某行 volume 为 NaN,close 正常"""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0],
            "High": [10.5, 9.5, 11.5],
            "Low": [9.8, 8.8, 10.8],
            "Close": [10.2, 9.2, 11.2],
            "Volume": [1000, float("nan"), 1100],
        },
        index=idx,
    )


def test_load_daily_drops_row_with_volume_nan():
    """回归测试 B: volume 字段为 NaN 的行应被剔除(close 正常也算缺失行)。"""
    df = load_daily("AAPL", "US", "2024-01-01", "2024-01-31", fetcher=_stub_fetch_volume_nan)
    assert len(df) == 2
    # 确认剩余行 volume 均非空
    assert df["volume"].notna().all()


# ── 富途分钟线数据源 ────────────────────────────────────────────────────────


def test_to_futu_code_converts_project_symbols():
    assert _to_futu_code("0700.HK", "HK") == "HK.00700"
    assert _to_futu_code("3690.HK", "HK") == "HK.03690"
    assert _to_futu_code("AAPL", "US") == "US.AAPL"
    assert _to_futu_code("HK.00700", "HK") == "HK.00700"


def test_load_minutes_normalizes_futu_style_fetcher():
    def fetcher(symbol, market, start, end, interval):
        assert (symbol, market, start, end, interval) == ("0700.HK", "HK", "2024-01-01", "2024-01-02", "1m")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
                "Volume": [1000, 1200],
            },
            index=pd.to_datetime(["2024-01-01 09:30:00", "2024-01-01 09:31:00"]),
        )

    df = load_minutes("0700.HK", "HK", "2024-01-01", "2024-01-02", "1m", fetcher=fetcher)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 100.5

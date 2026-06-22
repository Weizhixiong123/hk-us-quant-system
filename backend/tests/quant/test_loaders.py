import pandas as pd
from quant.data.loaders import load_daily


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

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

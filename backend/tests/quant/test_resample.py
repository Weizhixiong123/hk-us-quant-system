import pandas as pd
from quant.data.resample import resample_ohlcv


def _daily():
    idx = pd.to_datetime([
        "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
        "2024-01-08", "2024-01-09",
    ])
    return pd.DataFrame(
        {
            "open": [10, 11, 12, 13, 14, 20, 21],
            "high": [11, 12, 13, 14, 15, 22, 23],
            "low": [9, 10, 11, 12, 13, 19, 20],
            "close": [10.5, 11.5, 12.5, 13.5, 14.5, 21.5, 22.5],
            "volume": [100, 100, 100, 100, 100, 200, 200],
        },
        index=idx,
    )


def test_weekly_aggregation():
    wk = resample_ohlcv(_daily(), "W")
    # 第一周(1/1~1/5)
    first = wk.iloc[0]
    assert first["open"] == 10
    assert first["high"] == 15
    assert first["low"] == 9
    assert first["close"] == 14.5
    assert first["volume"] == 500


def test_monthly_has_single_bar_and_columns():
    mo = resample_ohlcv(_daily(), "ME")
    assert len(mo) == 1
    assert list(mo.columns) == ["open", "high", "low", "close", "volume"]
    assert mo.iloc[0]["close"] == 22.5

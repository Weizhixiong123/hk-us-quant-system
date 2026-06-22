import numpy as np
import pandas as pd

from app.strategies.trend_portfolio import FundamentalSnapshot
from quant.screening.portfolio_screener import (
    build_trend_snapshot,
    screen_portfolio,
)


def _uptrend_daily(days=900):
    idx = pd.date_range("2021-01-01", periods=days, freq="D")
    base = np.linspace(10, 80, days)  # 长期上行
    return pd.DataFrame(
        {
            "open": base,
            "high": base * 1.01,
            "low": base * 0.99,
            "close": base,
            "volume": np.full(days, 1_000_000),
        },
        index=idx,
    )


def _good_fundamentals():
    return FundamentalSnapshot(
        positive_profit_quarters=4,
        market_cap=3_000_000_000,
        has_major_risk=False,
    )


def test_build_trend_snapshot_fields_positive():
    snap = build_trend_snapshot(_uptrend_daily(), _good_fundamentals())
    assert snap.price > snap.ma60_month
    assert snap.ma5_week > snap.ma20_week  # 上行中短期周线在上


def test_screen_portfolio_passes_strong_uptrend():
    rows = [("AAPL", "US", _uptrend_daily(), _good_fundamentals())]
    hits = screen_portfolio(rows)
    assert hits[0].symbol == "AAPL"
    assert hits[0].passed is True
    assert hits[0].score == 1.0

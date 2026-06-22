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
    # days=2000 ≈ 66 个月，确保有 ≥60 根真实月线，断言验证的是真实均线而非 fallback 假象
    snap = build_trend_snapshot(_uptrend_daily(days=2000), _good_fundamentals())
    assert snap.price > snap.ma60_month
    assert snap.ma5_week > snap.ma20_week  # 上行中短期周线在上


def test_screen_portfolio_passes_strong_uptrend():
    rows = [("AAPL", "US", _uptrend_daily(days=2000), _good_fundamentals())]
    hits = screen_portfolio(rows)
    assert hits[0].symbol == "AAPL"
    assert hits[0].passed is True
    assert hits[0].score == 1.0


def test_screen_portfolio_rejects_short_history():
    """上市不足 5 年（约 41 个月日线）的标的：
    MACD 已有足够数据（≥26 月线）并通过，但 ma60_month 数据不足（<60 根月线）。
    修复前 ma60_month=0.0 导致 price>0.0 恒真（假阳性），修复后应被正确拦截（passed is False）。
    这是覆盖 Critical 均线 fallback 假阳性缺陷的回归测试。
    """
    rows = [("NEW_STOCK", "US", _uptrend_daily(days=1250), _good_fundamentals())]
    hits = screen_portfolio(rows)
    assert hits[0].passed is False

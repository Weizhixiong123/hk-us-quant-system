from quant.indicators.macd import macd, has_bullish_cross
from quant.indicators.trend import (
    sma,
    is_bullish_alignment,
    above_zero,
    max_drawdown_pct,
)


def test_macd_reexport_works():
    closes = [float(i) for i in range(1, 60)]
    points = macd(closes)
    assert points  # 非空
    assert hasattr(points[-1], "dif")


def test_sma_basic_and_insufficient():
    assert sma([2, 4, 6], 3) == 4.0
    assert sma([1, 2], 3) is None


def test_bullish_alignment():
    assert is_bullish_alignment(10, 8, 6) is True
    assert is_bullish_alignment(6, 8, 10) is False


def test_above_zero():
    assert above_zero(0.5, 0.2) is True
    assert above_zero(0.5, -0.1) is False


def test_max_drawdown_pct():
    # 100 -> 120 -> 90 ：最大回撤 (120-90)/120 = 25%
    assert round(max_drawdown_pct([100, 120, 90, 95]), 2) == 25.0
    assert max_drawdown_pct([100, 101, 102]) == 0.0

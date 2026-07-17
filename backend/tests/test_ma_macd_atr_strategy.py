from app.strategies.ma_macd_atr_intraday import has_bearish_cross, has_bullish_cross


def test_bullish_cross_compares_previous_dif_with_previous_dea():
    points = [(-1.0, 0.0, -2.0), (1.0, 0.5, 1.0)]

    assert has_bullish_cross(points) is True
    assert has_bearish_cross(points) is False


def test_bearish_cross_compares_previous_dif_with_previous_dea():
    points = [(1.0, 0.0, 2.0), (-1.0, -0.5, -1.0)]

    assert has_bearish_cross(points) is True
    assert has_bullish_cross(points) is False

from __future__ import annotations

from app.strategies.macd_intraday import (  # noqa: F401  复用,不重写
    MacdPoint,
    has_bearish_cross,
    has_bottom_divergence,
    has_bullish_cross,
    has_top_divergence,
    histogram_shrinking,
    macd,
)

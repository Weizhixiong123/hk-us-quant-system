from __future__ import annotations

from typing import Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(float(v) for v in window) / period


def is_bullish_alignment(short: float, mid: float, long: float) -> bool:
    return short > mid > long


def above_zero(dif: float, dea: float) -> bool:
    return dif > 0 and dea > 0


def max_drawdown_pct(closes: Sequence[float]) -> float:
    if not closes:
        return 0.0
    peak = float(closes[0])
    max_dd = 0.0
    for value in closes:
        price = float(value)
        peak = max(peak, price)
        if peak > 0:
            dd = (peak - price) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 6)

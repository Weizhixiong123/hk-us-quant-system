from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MacdPoint:
    dif: float
    dea: float
    hist: float


@dataclass(frozen=True)
class IntradayDecision:
    action: str
    confidence: float
    reasons: tuple[str, ...]


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []

    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def macd(
    closes: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[MacdPoint]:
    if len(closes) < slow_period:
        return []

    fast = ema(closes, fast_period)
    slow = ema(closes, slow_period)
    dif_values = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    dea_values = ema(dif_values, signal_period)
    return [
        MacdPoint(dif=dif, dea=dea, hist=(dif - dea) * 2)
        for dif, dea in zip(dif_values, dea_values)
    ]


def has_bullish_cross(points: Sequence[MacdPoint]) -> bool:
    if len(points) < 2:
        return False
    previous, current = points[-2], points[-1]
    return previous.dif <= previous.dea and current.dif > current.dea


def has_bearish_cross(points: Sequence[MacdPoint]) -> bool:
    if len(points) < 2:
        return False
    previous, current = points[-2], points[-1]
    return previous.dif >= previous.dea and current.dif < current.dea


def histogram_shrinking(
    points: Sequence[MacdPoint],
    side: str,
    bars: int = 3,
) -> bool:
    if bars < 2 or len(points) < bars:
        return False

    recent = [point.hist for point in points[-bars:]]
    if side == "long":
        return all(value < 0 for value in recent) and all(
            abs(left) > abs(right) for left, right in zip(recent, recent[1:])
        )
    if side == "short":
        return all(value > 0 for value in recent) and all(
            abs(left) > abs(right) for left, right in zip(recent, recent[1:])
        )
    raise ValueError("side must be 'long' or 'short'")


def _pivot_lows(values: Sequence[float], left: int = 2, right: int = 2) -> list[int]:
    pivots: list[int] = []
    for index in range(left, len(values) - right):
        window = values[index - left : index + right + 1]
        if values[index] == min(window):
            pivots.append(index)
    return pivots


def _pivot_highs(values: Sequence[float], left: int = 2, right: int = 2) -> list[int]:
    pivots: list[int] = []
    for index in range(left, len(values) - right):
        window = values[index - left : index + right + 1]
        if values[index] == max(window):
            pivots.append(index)
    return pivots


def has_bottom_divergence(
    lows: Sequence[float],
    macd_hist: Sequence[float],
    lookback: int = 28,
    threshold_pct: float = 0.003,
) -> bool:
    if len(lows) != len(macd_hist) or len(lows) < 8:
        return False

    start = max(0, len(lows) - lookback)
    local_lows = list(lows[start:])
    local_hist = list(macd_hist[start:])
    pivots = _pivot_lows(local_lows)
    if len(pivots) < 2:
        return False

    first, second = pivots[-2], pivots[-1]
    price_makes_lower_low = local_lows[second] < local_lows[first] * (1 - threshold_pct)
    hist_makes_higher_low = local_hist[second] > local_hist[first]
    return price_makes_lower_low and hist_makes_higher_low


def has_top_divergence(
    highs: Sequence[float],
    macd_hist: Sequence[float],
    lookback: int = 28,
    threshold_pct: float = 0.003,
) -> bool:
    if len(highs) != len(macd_hist) or len(highs) < 8:
        return False

    start = max(0, len(highs) - lookback)
    local_highs = list(highs[start:])
    local_hist = list(macd_hist[start:])
    pivots = _pivot_highs(local_highs)
    if len(pivots) < 2:
        return False

    first, second = pivots[-2], pivots[-1]
    price_makes_higher_high = local_highs[second] > local_highs[first] * (1 + threshold_pct)
    hist_makes_lower_high = local_hist[second] < local_hist[first]
    return price_makes_higher_high and hist_makes_lower_high


def build_intraday_decision(
    closes_15m: Sequence[float],
    lows_15m: Sequence[float],
    highs_15m: Sequence[float],
    closes_5m: Sequence[float],
    current_price: float,
    ma5_15m: float,
    side: str,
    within_trade_window: bool,
    shortable: bool = True,
) -> IntradayDecision:
    reasons: list[str] = []
    points_15m = macd(closes_15m)
    points_5m = macd(closes_5m)
    hist_15m = [point.hist for point in points_15m]

    if not within_trade_window:
        reasons.append("不在日内开仓时间窗")
    if side == "short" and not shortable:
        reasons.append("标的不在可做空名单")

    if side == "long":
        checks = {
            "15min 绿柱缩短": histogram_shrinking(points_15m, "long"),
            "15min 底背离": has_bottom_divergence(lows_15m[-len(hist_15m) :], hist_15m),
            "15min 金叉": has_bullish_cross(points_15m),
            "5min 金叉确认": has_bullish_cross(points_5m),
            "价格站上 15min 5MA": current_price > ma5_15m,
        }
    elif side == "short":
        checks = {
            "15min 红柱缩短": histogram_shrinking(points_15m, "short"),
            "15min 顶背离": has_top_divergence(highs_15m[-len(hist_15m) :], hist_15m),
            "15min 死叉": has_bearish_cross(points_15m),
            "5min 死叉确认": has_bearish_cross(points_5m),
            "价格跌破 15min 5MA": current_price < ma5_15m,
        }
    else:
        raise ValueError("side must be 'long' or 'short'")

    passed = [label for label, ok in checks.items() if ok]
    failed = [label for label, ok in checks.items() if not ok]
    reasons.extend(f"{label}通过" for label in passed)
    reasons.extend(f"{label}未满足" for label in failed)

    hard_blocked = any(reason in {"不在日内开仓时间窗", "标的不在可做空名单"} for reason in reasons)
    confidence = len(passed) / len(checks)
    action = side if confidence == 1 and not hard_blocked else "wait"
    return IntradayDecision(action=action, confidence=confidence, reasons=tuple(reasons))


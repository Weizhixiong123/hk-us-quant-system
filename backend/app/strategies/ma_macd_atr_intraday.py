from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MaAtrIntradayDecision:
    action: str  # "long" | "short" | "wait" | "exit"
    confidence: float
    reasons: tuple[str, ...]


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    result = [float(values[0])]
    for v in values[1:]:
        result.append(alpha * float(v) + (1.0 - alpha) * result[-1])
    return result


def macd(
    closes: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[tuple[float, float, float]]:
    """返回 [(dif, dea, hist)]。"""
    if len(closes) < slow_period:
        return []
    fast = ema(closes, fast_period)
    slow = ema(closes, slow_period)
    dif_values = [f - s for f, s in zip(fast, slow)]
    dea_values = ema(dif_values, signal_period)
    return [(dif, dea, (dif - dea) * 2) for dif, dea in zip(dif_values, dea_values)]


def has_bullish_cross(points: list[tuple[float, float, float]]) -> bool:
    if len(points) < 2:
        return False
    prev_dif, prev_dea, _ = points[-2]
    dif, dea, _ = points[-1]
    return prev_dif <= prev_dea and dif > dea


def has_bearish_cross(points: list[tuple[float, float, float]]) -> bool:
    if len(points) < 2:
        return False
    prev_dif, prev_dea, _ = points[-2]
    dif, dea, _ = points[-1]
    return prev_dif >= prev_dea and dif < dea


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 5) -> list[float]:
    """真实波幅 ATR。"""
    if len(closes) < 2:
        return []
    tr_list: list[float] = []
    for i in range(1, len(closes)):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
    if not tr_list:
        return []
    alpha = 2.0 / (period + 1)
    result = [tr_list[0]]
    for tr in tr_list[1:]:
        result.append(alpha * tr + (1 - alpha) * result[-1])
    return result


def build_ma_macd_atr_decision(
    closes_slow: Sequence[float],
    closes_mid: Sequence[float],
    closes_fast: Sequence[float],
    highs_fast: Sequence[float],
    lows_fast: Sequence[float],
    side: str,
    *,
    # 三周期 EMA 参数
    slow_fast_ema: int = 3,
    slow_slow_ema: int = 8,
    mid_fast_ema: int = 11,
    mid_slow_ema: int = 30,
    fast_fast_ema: int = 3,
    fast_slow_ema: int = 8,
    # MACD
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    # ATR
    atr_period: int = 5,
    atr_multiplier: float = 1.2,
) -> MaAtrIntradayDecision:
    """三周期 MA + MACD 金叉/死叉 + ATR 风控同步决策。

    开多:
        1h 慢 > 快   (大周期看多)
        10m 慢 > 快  (中周期确认)
        5m 快上穿慢  (小周期触发)
        MACD 金叉确认

    开空:反向。

    平多:
        5m 快下穿慢
        or MACD 死叉
        or 10m 反转
        or ATR 动态止损
    平空:反向。
    """
    if side not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")

    reasons: list[str] = []
    # === EMA 趋势判断 ===
    slow_ma_fast = ema(closes_slow, slow_fast_ema)
    slow_ma_slow = ema(closes_slow, slow_slow_ema)
    mid_ma_fast = ema(closes_mid, mid_fast_ema)
    mid_ma_slow = ema(closes_mid, mid_slow_ema)
    fast_ma_fast = ema(closes_fast, fast_fast_ema)
    fast_ma_slow = ema(closes_fast, fast_slow_ema)

    slow_bullish = len(slow_ma_fast) > 0 and len(slow_ma_slow) > 0 and slow_ma_fast[-1] > slow_ma_slow[-1]
    mid_bullish = len(mid_ma_fast) > 0 and len(mid_ma_slow) > 0 and mid_ma_fast[-1] > mid_ma_slow[-1]
    fast_bullish = len(fast_ma_fast) > 0 and len(fast_ma_slow) > 0 and fast_ma_fast[-1] > fast_ma_slow[-1]
    fast_cross_up = (
        len(fast_ma_fast) >= 2
        and len(fast_ma_slow) >= 2
        and fast_ma_fast[-2] <= fast_ma_slow[-2]
        and fast_ma_fast[-1] > fast_ma_slow[-1]
    )
    fast_cross_down = (
        len(fast_ma_fast) >= 2
        and len(fast_ma_slow) >= 2
        and fast_ma_fast[-2] >= fast_ma_slow[-2]
        and fast_ma_fast[-1] < fast_ma_slow[-1]
    )

    reasons.append(f"大周期EMA{'多头' if slow_bullish else '空头/未确认'}")
    reasons.append(f"中周期EMA{'多头' if mid_bullish else '空头/未确认'}")
    reasons.append(f"小周期EMA{'多头' if fast_bullish else '空头/未确认'}")

    # === MACD 金叉/死叉 ===
    points = macd(closes_fast, fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal)
    macd_bullish_cross = has_bullish_cross(points) if points else False
    macd_bearish_cross = has_bearish_cross(points) if points else False
    if macd_bullish_cross:
        reasons.append("MACD 金叉")
    elif macd_bearish_cross:
        reasons.append("MACD 死叉")

    # === ATR 风控 (只有开仓后才判断) ===
    atr_values = atr(highs_fast, lows_fast, closes_fast, period=atr_period)
    atr_value = atr_values[-1] if atr_values else 0.0

    if side == "long":
        # 多头入场条件
        long_ok = slow_bullish and mid_bullish and (fast_cross_up or fast_bullish) and macd_bullish_cross
        confidence = sum([slow_bullish, mid_bullish, fast_bullish, macd_bullish_cross]) / 4.0
        action = "long" if long_ok else "wait"
        if atr_value > 0:
            entry_price = float(closes_fast[-1]) if closes_fast else 0.0
            stop_price = entry_price - atr_value * atr_multiplier
            take_price = entry_price + atr_value * atr_multiplier
            reasons.append(f"ATR {atr_value:.2f} 止损 {stop_price:.2f} 止盈 {take_price:.2f}")
        return MaAtrIntradayDecision(action=action, confidence=confidence, reasons=tuple(reasons))
    else:
        short_ok = (not slow_bullish) and (not mid_bullish) and (fast_cross_down or not fast_bullish) and macd_bearish_cross
        confidence = sum([not slow_bullish, not mid_bullish, not fast_bullish, macd_bearish_cross]) / 4.0
        action = "short" if short_ok else "wait"
        if atr_value > 0:
            entry_price = float(closes_fast[-1]) if closes_fast else 0.0
            stop_price = entry_price + atr_value * atr_multiplier
            take_price = entry_price - atr_value * atr_multiplier
            reasons.append(f"ATR {atr_value:.2f} 止损 {stop_price:.2f} 止盈 {take_price:.2f}")
        return MaAtrIntradayDecision(action=action, confidence=confidence, reasons=tuple(reasons))

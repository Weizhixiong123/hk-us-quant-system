from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from app.strategies.ma_macd_atr_intraday import build_ma_macd_atr_decision
from quant.live.clock import Market, is_intraday_entry_window
from quant.screening.intraday_screener import IntradayCandidate


MaAtrAction = Literal["wait", "enter_long", "enter_short", "exit_long", "exit_short"]
PositionSide = Literal["long", "short"]


@dataclass(frozen=True)
class MaAtrEntrySignal:
    action: MaAtrAction
    symbol: str
    side: PositionSide | None
    confidence: float
    reasons: tuple[str, ...]
    atr_stop: float | None  # ATR 止损价


@dataclass(frozen=True)
class MaAtrPosition:
    symbol: str
    side: PositionSide
    quantity: int
    avg_price: float
    highest_since_entry: float  # 多头入场以来的最高价(用于动态止盈)


def build_ma_atr_premarket_watchlist(
    candidates: Sequence[IntradayCandidate],
    *,
    min_turnover: float = 5_000_000.0,
    min_amplitude_pct: float = 2.0,
    max_amplitude_pct: float = 8.0,
    min_price: float = 2.0,
    min_turnover_rate: float = 0.0,
) -> list[str]:
    from quant.live.intraday import build_premarket_watchlist
    return build_premarket_watchlist(
        candidates,
        min_turnover=min_turnover,
        min_amplitude_pct=min_amplitude_pct,
        max_amplitude_pct=max_amplitude_pct,
        min_price=min_price,
        min_turnover_rate=min_turnover_rate,
    )


def evaluate_ma_atr_entry_signal(
    symbol: str,
    market: Market,
    at: datetime,
    closes_slow: Sequence[float],
    closes_mid: Sequence[float],
    closes_fast: Sequence[float],
    highs_fast: Sequence[float],
    lows_fast: Sequence[float],
    *,
    slow_fast_ema: int = 3,
    slow_slow_ema: int = 8,
    mid_fast_ema: int = 11,
    mid_slow_ema: int = 30,
    fast_fast_ema: int = 3,
    fast_slow_ema: int = 8,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    atr_period: int = 5,
    atr_multiplier: float = 1.2,
    open_after_minutes: int = 30,
    close_before_minutes: int = 90,
) -> MaAtrEntrySignal:
    """策略三入场评估。

    1h 定方向 → 10m 确认趋势 → 5m 触发 → MACD 确认 → ATR 风控。
    """
    within_window = is_intraday_entry_window(
        at, market,
        open_after_minutes=open_after_minutes,
        close_before_minutes=close_before_minutes,
    )
    if not within_window:
        return MaAtrEntrySignal("wait", symbol, None, 0.0, ("不在交易时段",), None)

    long_decision = build_ma_macd_atr_decision(
        closes_slow, closes_mid, closes_fast, highs_fast, lows_fast, "long",
        slow_fast_ema=slow_fast_ema, slow_slow_ema=slow_slow_ema,
        mid_fast_ema=mid_fast_ema, mid_slow_ema=mid_slow_ema,
        fast_fast_ema=fast_fast_ema, fast_slow_ema=fast_slow_ema,
        macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal,
        atr_period=atr_period, atr_multiplier=atr_multiplier,
    )
    if long_decision.action == "long":
        return MaAtrEntrySignal("enter_long", symbol, "long", long_decision.confidence, long_decision.reasons, None)

    short_decision = build_ma_macd_atr_decision(
        closes_slow, closes_mid, closes_fast, highs_fast, lows_fast, "short",
        slow_fast_ema=slow_fast_ema, slow_slow_ema=slow_slow_ema,
        mid_fast_ema=mid_fast_ema, mid_slow_ema=mid_slow_ema,
        fast_fast_ema=fast_fast_ema, fast_slow_ema=fast_slow_ema,
        macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal,
        atr_period=atr_period, atr_multiplier=atr_multiplier,
    )
    if short_decision.action == "short":
        return MaAtrEntrySignal("enter_short", symbol, "short", short_decision.confidence, short_decision.reasons, None)

    return MaAtrEntrySignal("wait", symbol, None, long_decision.confidence, long_decision.reasons, None)


def evaluate_ma_atr_exit_signal(
    position: MaAtrPosition,
    closes_slow: Sequence[float],
    closes_mid: Sequence[float],
    closes_fast: Sequence[float],
    highs_fast: Sequence[float],
    lows_fast: Sequence[float],
    *,
    fast_fast_ema: int = 3,
    fast_slow_ema: int = 8,
    mid_fast_ema: int = 11,
    mid_slow_ema: int = 30,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    atr_period: int = 5,
    atr_multiplier: float = 1.2,
    stop_loss_pct: float = 1.5,
    take_profit_pct: float = 3.0,
    trailing_enabled: bool = True,
    trailing_start_pct: float = 2.0,
    trailing_stop_pct: float = 1.0,
) -> tuple[MaAtrAction, tuple[str, ...]]:
    """策略三出场评估。

    平多 → 5m 反转 / MACD 死叉 / 10m 反转 / 止损 / 止盈 / ATR 止损 / 移动止盈。
    平空 → 反向。
    """
    from app.strategies.ma_macd_atr_intraday import ema, macd, has_bearish_cross, has_bullish_cross, atr

    if not closes_fast:
        return "wait", ("无最新价",)
    last_price = float(closes_fast[-1])

    reasons: list[str] = []

    # 小周期 EMA 反转
    fast_ma = ema(closes_fast, fast_fast_ema)
    slow_ma = ema(closes_fast, fast_slow_ema)
    if len(fast_ma) >= 2 and len(slow_ma) >= 2:
        if position.side == "long" and fast_ma[-2] >= slow_ma[-2] and fast_ma[-1] < slow_ma[-1]:
            reasons.append("5分钟 EMA 下穿")
        if position.side == "short" and fast_ma[-2] <= slow_ma[-2] and fast_ma[-1] > slow_ma[-1]:
            reasons.append("5分钟 EMA 上穿")

    # MACD 反转
    points = macd(closes_fast, fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal)
    if points:
        if position.side == "long" and has_bearish_cross(points):
            reasons.append("MACD 死叉")
        if position.side == "short" and has_bullish_cross(points):
            reasons.append("MACD 金叉")

    # 中周期 EMA 反转
    mid_fast = ema(closes_mid, mid_fast_ema)
    mid_slow = ema(closes_mid, mid_slow_ema)
    if len(mid_fast) >= 2 and len(mid_slow) >= 2:
        if position.side == "long" and mid_fast[-2] >= mid_slow[-2] and mid_fast[-1] < mid_slow[-1]:
            reasons.append("10分钟 EMA 下穿")
        if position.side == "short" and mid_fast[-2] <= mid_slow[-2] and mid_fast[-1] > mid_slow[-1]:
            reasons.append("10分钟 EMA 上穿")

    # 固定止损 / 止盈
    pnl_pct = ((last_price - position.avg_price) / position.avg_price) * 100.0 if position.side == "long" \
        else ((position.avg_price - last_price) / position.avg_price) * 100.0
    if pnl_pct <= -stop_loss_pct:
        reasons.append(f"固定止损 {pnl_pct:.2f}%")
    if pnl_pct >= take_profit_pct:
        reasons.append(f"固定止盈 {pnl_pct:.2f}%")

    # ATR 止损
    atr_values = atr(highs_fast, lows_fast, closes_fast, period=atr_period)
    if atr_values:
        atr_value = atr_values[-1]
        if position.side == "long":
            atr_stop = position.avg_price - atr_value * atr_multiplier
            if last_price <= atr_stop:
                reasons.append(f"ATR 止损(atr={atr_value:.2f})")
        else:
            atr_stop = position.avg_price + atr_value * atr_multiplier
            if last_price >= atr_stop:
                reasons.append(f"ATR 止损(atr={atr_value:.2f})")

    # 移动止盈
    if trailing_enabled and position.highest_since_entry > 0:
        if position.side == "long":
            peak_pct = ((position.highest_since_entry - position.avg_price) / position.avg_price) * 100.0
            if peak_pct >= trailing_start_pct:
                pullback_pct = ((position.highest_since_entry - last_price) / position.highest_since_entry) * 100.0
                if pullback_pct >= trailing_stop_pct:
                    reasons.append(f"移动止盈(回撤 {pullback_pct:.2f}%)")
        else:
            peak_pct = ((position.avg_price - position.highest_since_entry) / position.avg_price) * 100.0
            if peak_pct >= trailing_start_pct:
                pullback_pct = ((last_price - position.highest_since_entry) / position.highest_since_entry) * 100.0
                if pullback_pct >= trailing_stop_pct:
                    reasons.append(f"移动止盈(回撤 {pullback_pct:.2f}%)")

    if reasons:
        action = "exit_long" if position.side == "long" else "exit_short"
        return action, tuple(reasons)
    return "wait", ("继续持仓",)

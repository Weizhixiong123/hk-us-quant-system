from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from app.strategies.macd_intraday import build_intraday_decision, macd
from quant.live.clock import Market, is_intraday_entry_window
from quant.screening.intraday_screener import IntradayCandidate, screen_intraday


IntradayAction = Literal["wait", "enter_long", "enter_short", "exit_half", "exit_all"]
PositionSide = Literal["long", "short"]
IntradayMomentum = Literal["rising", "falling", "mixed"]


@dataclass(frozen=True)
class IntradayEntrySignal:
    action: IntradayAction
    symbol: str
    side: PositionSide | None
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class IntradayPosition:
    symbol: str
    side: PositionSide
    quantity: int
    avg_price: float
    first_take_profit_done: bool = False


@dataclass(frozen=True)
class IntradayExitSignal:
    action: IntradayAction
    symbol: str
    quantity: int
    reasons: tuple[str, ...]


def build_premarket_watchlist(
    candidates: Sequence[IntradayCandidate],
    *,
    min_turnover: float = 5_000_000.0,
    min_amplitude_pct: float = 2.0,
    max_amplitude_pct: float = 8.0,
    min_price: float = 2.0,
    min_turnover_rate: float = 0.0,
) -> list[str]:
    hits = screen_intraday(
        candidates,
        min_turnover=min_turnover,
        min_amplitude_pct=min_amplitude_pct,
        max_amplitude_pct=max_amplitude_pct,
        min_price=min_price,
        min_turnover_rate=min_turnover_rate,
    )
    return [hit.symbol for hit in hits if hit.passed]


def evaluate_intraday_entry_signal(
    symbol: str,
    market: Market,
    at: datetime,
    closes_slow: Sequence[float],
    closes_mid: Sequence[float],
    closes_fast: Sequence[float],
    *,
    fast_ema: int = 12,
    slow_ema: int = 26,
    signal_ema: int = 9,
    slow_k_minutes: int = 15,
    mid_k_minutes: int = 5,
    fast_k_minutes: int = 3,
    open_after_minutes: int = 30,
    close_before_minutes: int = 90,
) -> IntradayEntrySignal:
    """三周期 MACD 柱动量同步入场(默认 15m/5m/3m,周期可配置)。

    先判多(三周期柱同步抬高),不成立再判空(三周期柱同步下降)。
    """
    within_window = is_intraday_entry_window(
        at, market,
        open_after_minutes=open_after_minutes,
        close_before_minutes=close_before_minutes,
    )
    long_decision = build_intraday_decision(
        closes_slow=closes_slow,
        closes_mid=closes_mid,
        closes_fast=closes_fast,
        side="long",
        within_trade_window=within_window,
        fast_period=fast_ema,
        slow_period=slow_ema,
        signal_period=signal_ema,
        slow_k_minutes=slow_k_minutes,
        mid_k_minutes=mid_k_minutes,
        fast_k_minutes=fast_k_minutes,
    )
    if long_decision.action == "long":
        return IntradayEntrySignal("enter_long", symbol, "long", long_decision.confidence, long_decision.reasons)

    short_decision = build_intraday_decision(
        closes_slow=closes_slow,
        closes_mid=closes_mid,
        closes_fast=closes_fast,
        side="short",
        within_trade_window=within_window,
        fast_period=fast_ema,
        slow_period=slow_ema,
        signal_period=signal_ema,
        slow_k_minutes=slow_k_minutes,
        mid_k_minutes=mid_k_minutes,
        fast_k_minutes=fast_k_minutes,
    )
    if short_decision.action == "short":
        return IntradayEntrySignal("enter_short", symbol, "short", short_decision.confidence, short_decision.reasons)

    return IntradayEntrySignal("wait", symbol, None, long_decision.confidence, long_decision.reasons)


def evaluate_intraday_exit_signal(
    position: IntradayPosition,
    momentum: IntradayMomentum,
) -> IntradayExitSignal:
    """三周期 MACD 柱同步反向 → 立即全平。

    - 持多 + 三周期柱同步下降 → 平多
    - 持空 + 三周期柱同步抬高 → 平空
    """
    if position.side == "long" and momentum == "falling":
        return _exit_all(position, "三周期 MACD 柱同步下降,平多")
    if position.side == "short" and momentum == "rising":
        return _exit_all(position, "三周期 MACD 柱同步抬高,平空")

    return IntradayExitSignal(
        action="wait",
        symbol=position.symbol,
        quantity=0,
        reasons=("日内持仓继续观察",),
    )


def three_period_macd_momentum(
    closes_slow: Sequence[float],
    closes_mid: Sequence[float],
    closes_fast: Sequence[float],
    *,
    fast_ema: int = 12,
    slow_ema: int = 26,
    signal_ema: int = 9,
) -> IntradayMomentum:
    """返回三周期 MACD 柱体的共同方向,供实盘与回测复用。"""
    directions: list[IntradayMomentum] = []
    for closes in (closes_slow, closes_mid, closes_fast):
        points = macd(
            closes,
            fast_period=fast_ema,
            slow_period=slow_ema,
            signal_period=signal_ema,
        )
        if len(points) < 2 or points[-1].hist == points[-2].hist:
            return "mixed"
        directions.append("rising" if points[-1].hist > points[-2].hist else "falling")
    if all(direction == "rising" for direction in directions):
        return "rising"
    if all(direction == "falling" for direction in directions):
        return "falling"
    return "mixed"


def _exit_all(position: IntradayPosition, reason: str) -> IntradayExitSignal:
    return IntradayExitSignal(
        action="exit_all",
        symbol=position.symbol,
        quantity=position.quantity,
        reasons=(reason,),
    )

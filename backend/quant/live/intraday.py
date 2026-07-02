from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from app.strategies.macd_intraday import build_intraday_decision
from quant.live.clock import Market, is_intraday_entry_window
from quant.screening.intraday_screener import IntradayCandidate, screen_intraday


IntradayAction = Literal["wait", "enter_long", "enter_short", "exit_half", "exit_all"]
PositionSide = Literal["long", "short"]


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
    min_turnover: float = 5_000_000.0,
) -> list[str]:
    hits = screen_intraday(candidates, min_turnover)
    return [hit.symbol for hit in hits if hit.passed]


def evaluate_intraday_entry_signal(
    symbol: str,
    market: Market,
    at: datetime,
    closes_15m: Sequence[float],
    closes_5m: Sequence[float],
    closes_3m: Sequence[float],
) -> IntradayEntrySignal:
    """三周期(15m/5m/3m)MACD 柱动量同步入场。

    先判多(三周期柱同步抬高),不成立再判空(三周期柱同步下降)。
    """
    within_window = is_intraday_entry_window(at, market)
    long_decision = build_intraday_decision(
        closes_15m=closes_15m,
        closes_5m=closes_5m,
        closes_3m=closes_3m,
        side="long",
        within_trade_window=within_window,
    )
    if long_decision.action == "long":
        return IntradayEntrySignal("enter_long", symbol, "long", long_decision.confidence, long_decision.reasons)

    short_decision = build_intraday_decision(
        closes_15m=closes_15m,
        closes_5m=closes_5m,
        closes_3m=closes_3m,
        side="short",
        within_trade_window=within_window,
    )
    if short_decision.action == "short":
        return IntradayEntrySignal("enter_short", symbol, "short", short_decision.confidence, short_decision.reasons)

    return IntradayEntrySignal("wait", symbol, None, long_decision.confidence, long_decision.reasons)


def evaluate_intraday_exit_signal(
    position: IntradayPosition,
    momentum: Literal["rising", "falling", "mixed"],
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


def _exit_all(position: IntradayPosition, reason: str) -> IntradayExitSignal:
    return IntradayExitSignal(
        action="exit_all",
        symbol=position.symbol,
        quantity=position.quantity,
        reasons=(reason,),
    )

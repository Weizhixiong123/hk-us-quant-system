from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from app.strategies.macd_intraday import build_intraday_decision
from quant.live.clock import Market, is_force_close_window, is_intraday_entry_window
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
    pnl_pct: float
    stopped_today: bool
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
    lows_15m: Sequence[float],
    highs_15m: Sequence[float],
    closes_5m: Sequence[float],
    current_price: float,
    ma5_15m: float,
    side: PositionSide = "long",
    shortable: bool = True,
) -> IntradayEntrySignal:
    decision = build_intraday_decision(
        closes_15m=closes_15m,
        lows_15m=lows_15m,
        highs_15m=highs_15m,
        closes_5m=closes_5m,
        current_price=current_price,
        ma5_15m=ma5_15m,
        side=side,
        within_trade_window=is_intraday_entry_window(at, market),
        shortable=shortable,
    )
    if decision.action == "long":
        return IntradayEntrySignal("enter_long", symbol, "long", decision.confidence, decision.reasons)
    if decision.action == "short":
        return IntradayEntrySignal("enter_short", symbol, "short", decision.confidence, decision.reasons)
    return IntradayEntrySignal("wait", symbol, None, decision.confidence, decision.reasons)


def evaluate_intraday_exit_signal(
    position: IntradayPosition,
    market: Market,
    at: datetime,
    current_price: float,
    reverse_cross: bool = False,
    stop_loss_pct: float = 1.5,
    take_profit_1_pct: float = 2.0,
    take_profit_2_pct: float = 3.5,
) -> IntradayExitSignal:
    pnl_pct = _pnl_pct(position, current_price)

    if pnl_pct <= -abs(stop_loss_pct):
        return _exit_all(position, pnl_pct, True, "触发日内止损，平仓并记录当日禁开")
    if pnl_pct >= take_profit_2_pct:
        return _exit_all(position, pnl_pct, False, "触发第二档止盈，全部平仓")
    if reverse_cross:
        return _exit_all(position, pnl_pct, False, "MACD 反向交叉，全部平仓")
    if is_force_close_window(at, market):
        return _exit_all(position, pnl_pct, False, "收盘前 10 分钟强制清仓")
    if pnl_pct >= take_profit_1_pct and not position.first_take_profit_done:
        return IntradayExitSignal(
            action="exit_half",
            symbol=position.symbol,
            quantity=max(1, position.quantity // 2),
            pnl_pct=round(pnl_pct, 2),
            stopped_today=False,
            reasons=("触发第一档止盈，平半仓",),
        )

    return IntradayExitSignal(
        action="wait",
        symbol=position.symbol,
        quantity=0,
        pnl_pct=round(pnl_pct, 2),
        stopped_today=False,
        reasons=("日内持仓继续观察",),
    )


def _exit_all(
    position: IntradayPosition,
    pnl_pct: float,
    stopped_today: bool,
    reason: str,
) -> IntradayExitSignal:
    return IntradayExitSignal(
        action="exit_all",
        symbol=position.symbol,
        quantity=position.quantity,
        pnl_pct=round(pnl_pct, 2),
        stopped_today=stopped_today,
        reasons=(reason,),
    )


def _pnl_pct(position: IntradayPosition, current_price: float) -> float:
    if position.avg_price <= 0:
        return 0.0
    if position.side == "long":
        return (current_price - position.avg_price) / position.avg_price * 100
    return (position.avg_price - current_price) / position.avg_price * 100

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import pandas as pd

from app.strategies.trend_portfolio import FundamentalSnapshot
from quant.live.position_manager import EntryStage
from quant.screening.portfolio_screener import PortfolioHit, screen_portfolio


TrendAction = Literal["wait", "enter_first", "enter_add", "exit_half", "exit_all"]


@dataclass(frozen=True)
class DailyTimingSnapshot:
    close: float
    low: float
    ma20: float
    ma30: float
    previous_close: float
    volume: float
    avg_volume20: float
    macd_bearish_break: bool = False
    macd_recover_cross: bool = False
    short_term_gain_pct: float = 0.0


@dataclass(frozen=True)
class TrendEntrySignal:
    action: TrendAction
    symbol: str
    stage: EntryStage | None
    pullback_confirmed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TrendPosition:
    symbol: str
    quantity: int
    avg_price: float
    holding_days: int
    take_profit_done: bool = False


@dataclass(frozen=True)
class TrendExitSignal:
    action: TrendAction
    symbol: str
    quantity: int
    pnl_pct: float
    reasons: tuple[str, ...]


def build_month_end_watchlist(
    rows: Sequence[tuple[str, str, pd.DataFrame, FundamentalSnapshot]],
) -> list[str]:
    hits = screen_portfolio(rows)
    return [hit.symbol for hit in _passed_by_score(hits)]


def evaluate_trend_entry_signal(
    symbol: str,
    timing: DailyTimingSnapshot,
    stage: EntryStage,
    pullback_tolerance_pct: float = 1.0,
    volume_selloff_multiple: float = 1.5,
    hot_gain_block_pct: float = 40.0,
) -> TrendEntrySignal:
    pullback_confirmed = _pullback_confirmed(timing, pullback_tolerance_pct)
    macd_ok = not timing.macd_bearish_break or timing.macd_recover_cross
    volume_ok = not _volume_selloff(timing, volume_selloff_multiple)
    gain_ok = timing.short_term_gain_pct <= hot_gain_block_pct

    checks = {
        "日线回踩 20/30 日均线企稳": pullback_confirmed,
        "MACD 未破位或已重新金叉": macd_ok,
        "无放量大跌": volume_ok,
        "短期涨幅未过热": gain_ok,
    }
    reasons = tuple(f"{label}{'通过' if ok else '未满足'}" for label, ok in checks.items())
    if all(checks.values()):
        return TrendEntrySignal(
            action="enter_first" if stage == "first" else "enter_add",
            symbol=symbol,
            stage=stage,
            pullback_confirmed=pullback_confirmed,
            reasons=reasons,
        )
    return TrendEntrySignal(
        action="wait",
        symbol=symbol,
        stage=None,
        pullback_confirmed=pullback_confirmed,
        reasons=reasons,
    )


def evaluate_trend_exit_signal(
    position: TrendPosition,
    current_price: float,
    monthly_below_ma60_months: int = 0,
    weekly_ma5: float = 0.0,
    weekly_ma10: float = 0.0,
    monthly_macd_dif: float = 0.0,
    monthly_macd_dea: float = 0.0,
    top_divergence: bool = False,
    symbol_drawdown_pct: float = 0.0,
    max_symbol_drawdown_pct: float = 18.0,
    take_profit_pct: float = 20.0,
    rebalance_months: int = 6,
) -> TrendExitSignal:
    pnl_pct = _pnl_pct(position.avg_price, current_price)
    if symbol_drawdown_pct >= max_symbol_drawdown_pct:
        return _exit_all(position, pnl_pct, "单标的回撤触发止损")
    if monthly_below_ma60_months >= 2:
        return _exit_all(position, pnl_pct, "月线连续跌破 60 月线，清仓")
    if weekly_ma5 > 0 and weekly_ma10 > 0 and weekly_ma5 < weekly_ma10:
        return _exit_all(position, pnl_pct, "周线 5 周下穿 10 周，清仓")
    if monthly_macd_dif < 0 or monthly_macd_dea < 0:
        return _exit_all(position, pnl_pct, "月线 MACD 跌破零轴，清仓")
    if top_divergence:
        return _exit_all(position, pnl_pct, "周/月线顶背离，清仓")
    if position.holding_days >= rebalance_months * 30:
        return _exit_all(position, pnl_pct, "持仓满调仓周期，清仓复核")
    if pnl_pct >= take_profit_pct and not position.take_profit_done:
        return TrendExitSignal(
            action="exit_half",
            symbol=position.symbol,
            quantity=max(1, position.quantity // 2),
            pnl_pct=round(pnl_pct, 2),
            reasons=("中长线盈利达标，减半锁定利润",),
        )
    return TrendExitSignal(
        action="wait",
        symbol=position.symbol,
        quantity=0,
        pnl_pct=round(pnl_pct, 2),
        reasons=("中长线持仓继续观察",),
    )


def _passed_by_score(hits: Sequence[PortfolioHit]) -> list[PortfolioHit]:
    return sorted((hit for hit in hits if hit.passed), key=lambda hit: hit.score, reverse=True)


def _pullback_confirmed(timing: DailyTimingSnapshot, tolerance_pct: float) -> bool:
    tolerance = max(tolerance_pct, 0.0) / 100
    for average in (timing.ma20, timing.ma30):
        if average > 0 and timing.low <= average * (1 + tolerance) and timing.close >= average:
            return True
    return False


def _volume_selloff(timing: DailyTimingSnapshot, volume_multiple: float) -> bool:
    if timing.previous_close <= 0 or timing.avg_volume20 <= 0:
        return False
    return timing.close < timing.previous_close and timing.volume > timing.avg_volume20 * volume_multiple


def _exit_all(position: TrendPosition, pnl_pct: float, reason: str) -> TrendExitSignal:
    return TrendExitSignal(
        action="exit_all",
        symbol=position.symbol,
        quantity=position.quantity,
        pnl_pct=round(pnl_pct, 2),
        reasons=(reason,),
    )


def _pnl_pct(avg_price: float, current_price: float) -> float:
    if avg_price <= 0:
        return 0.0
    return (current_price - avg_price) / avg_price * 100

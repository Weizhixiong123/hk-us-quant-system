from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from quant.live.clock import (
    HolidayCalendar,
    Market,
    close_review_time,
    is_force_close_window,
    is_bar_close,
    is_intraday_entry_window,
    is_market_open,
    is_month_end_rebalance_day,
    is_trading_day,
    market_time,
    premarket_scan_time,
)


ScheduleHook = Literal[
    "intraday_premarket_scan",
    "intraday_3m_signal",
    "intraday_3m_exit",
    "intraday_force_close",
    "portfolio_daily_review",
    "portfolio_month_end_scan",
]


@dataclass(frozen=True)
class SchedulerAction:
    hook: ScheduleHook
    strategy_id: str
    market: Market
    scheduled_for: datetime
    reason: str


class LiveScheduler:
    def __init__(
        self,
        markets: Sequence[Market] = ("HK", "US"),
        holidays: HolidayCalendar | None = None,
        open_after_minutes: int = 30,
        close_before_minutes: int = 90,
        bar_interval_minutes: int = 3,
    ) -> None:
        self.markets = tuple(markets)
        self.holidays = holidays
        self.open_after_minutes = open_after_minutes
        self.close_before_minutes = close_before_minutes
        self.bar_interval_minutes = bar_interval_minutes
        self._dispatched: set[tuple[ScheduleHook, Market, datetime]] = set()

    def due_actions(self, at: datetime) -> list[SchedulerAction]:
        actions = build_due_actions(
            at,
            self.markets,
            self.holidays,
            self.open_after_minutes,
            self.close_before_minutes,
            self.bar_interval_minutes,
        )
        fresh_actions: list[SchedulerAction] = []
        for action in actions:
            key = (action.hook, action.market, _minute(action.scheduled_for))
            if key in self._dispatched:
                continue
            self._dispatched.add(key)
            fresh_actions.append(action)
        return fresh_actions

    def reset(self) -> None:
        self._dispatched.clear()


def build_due_actions(
    at: datetime,
    markets: Sequence[Market] = ("HK", "US"),
    holidays: HolidayCalendar | None = None,
    open_after_minutes: int = 30,
    close_before_minutes: int = 90,
    bar_interval_minutes: int = 3,
) -> list[SchedulerAction]:
    actions: list[SchedulerAction] = []
    for market in markets:
        local = market_time(at, market)
        day = local.date()
        if not is_trading_day(day, market, holidays):
            continue

        if _same_minute(local, premarket_scan_time(day, market)):
            actions.append(
                SchedulerAction(
                    hook="intraday_premarket_scan",
                    strategy_id="intraday_macd",
                    market=market,
                    scheduled_for=_minute(local),
                    reason="盘前刷新日内候选池",
                )
            )

        if is_force_close_window(local, market, holidays):
            actions.append(
                SchedulerAction(
                    hook="intraday_force_close",
                    strategy_id="intraday_macd",
                    market=market,
                    scheduled_for=_minute(local),
                    reason="尾盘强制清仓日内持仓",
                )
            )
        elif is_market_open(local, market, holidays) and is_bar_close(local, bar_interval_minutes, market):
            if is_intraday_entry_window(
                local,
                market,
                open_after_minutes=open_after_minutes,
                close_before_minutes=close_before_minutes,
                holidays=holidays,
            ):
                actions.append(
                    SchedulerAction(
                        hook="intraday_3m_signal",
                        strategy_id="intraday_macd",
                        market=market,
                        scheduled_for=_minute(local),
                        reason=f"{bar_interval_minutes}min 收线后检查日内开仓(三周期柱动量)",
                    )
                )
            actions.append(
                SchedulerAction(
                    hook="intraday_3m_exit",
                    strategy_id="intraday_macd",
                    market=market,
                    scheduled_for=_minute(local),
                    reason=f"{bar_interval_minutes}min 收线后检查日内持仓退出",
                )
            )

        if _same_minute(local, close_review_time(day, market)):
            if is_month_end_rebalance_day(day, market, holidays):
                actions.append(
                    SchedulerAction(
                        hook="portfolio_month_end_scan",
                        strategy_id="trend_portfolio",
                        market=market,
                        scheduled_for=_minute(local),
                        reason="月末最后交易日重跑中长线选股",
                    )
                )
            actions.append(
                SchedulerAction(
                    hook="portfolio_daily_review",
                    strategy_id="trend_portfolio",
                    market=market,
                    scheduled_for=_minute(local),
                    reason="收盘后检查中长线择时与出场",
                )
            )

    return actions


def _same_minute(left: datetime, right: datetime) -> bool:
    return _minute(left) == _minute(right)


def _minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)

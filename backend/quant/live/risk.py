from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal, Sequence

from quant.live.clock import Market


OrderPurpose = Literal["open", "close"]


@dataclass(frozen=True)
class LiveRiskDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass
class PdtTracker:
    max_day_trades: int = 3
    trades: list[date] = field(default_factory=list)

    def record_day_trade(self, day: date) -> None:
        self.trades.append(day)

    def remaining(self, as_of: date) -> int:
        cutoff = _business_days_back(as_of, 4)
        used = sum(1 for day in self.trades if cutoff <= day <= as_of)
        return max(self.max_day_trades - used, 0)


def evaluate_live_order_risk(
    symbol: str,
    market: Market,
    purpose: OrderPurpose,
    gateway_connected: bool,
    daily_loss_pct: float,
    stopped_symbols_today: Sequence[str],
    max_daily_loss_pct: float = 3.0,
    pdt_trades_remaining: int | None = None,
    is_short: bool = False,
    shortable: bool = True,
    consecutive_order_failures: int = 0,
    max_order_failures: int = 3,
) -> LiveRiskDecision:
    blocks: list[str] = []
    normalized_symbol = symbol.strip().upper()
    stopped_symbols = {item.strip().upper() for item in stopped_symbols_today}

    if not gateway_connected:
        blocks.append("网关未连接，暂停下单")
    if consecutive_order_failures >= max_order_failures:
        blocks.append("连续下单失败次数过多，暂停自动下单")

    if purpose == "open":
        if daily_loss_pct <= -abs(max_daily_loss_pct):
            blocks.append("触发单日账户最大亏损")
        if normalized_symbol in stopped_symbols:
            blocks.append("该标的当日已止损，禁止再开仓")
        if market == "US" and pdt_trades_remaining is not None and pdt_trades_remaining <= 0:
            blocks.append("美股 PDT 日内交易额度不足")
        if is_short and not shortable:
            blocks.append("标的不满足可做空校验")

    return LiveRiskDecision(
        allowed=not blocks,
        reasons=tuple(blocks or ["实盘风控通过"]),
    )


def _business_days_back(day: date, days_back: int) -> date:
    current = day
    remaining = days_back
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current

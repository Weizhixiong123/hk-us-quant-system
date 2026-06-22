from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_intraday_order(
    daily_loss_pct: float,
    max_daily_loss_pct: float,
    open_intraday_positions: int,
    max_intraday_positions: int,
    symbol_stopped_today: bool,
    is_short: bool,
    shortable: bool,
    pdt_trades_remaining: int | None,
) -> RiskDecision:
    blocks: list[str] = []
    if daily_loss_pct <= -abs(max_daily_loss_pct):
        blocks.append("触发单日账户最大亏损")
    if open_intraday_positions >= max_intraday_positions:
        blocks.append("日内同时持仓数量已达上限")
    if symbol_stopped_today:
        blocks.append("该标的当日已止损，禁止再开仓")
    if is_short and not shortable:
        blocks.append("标的不满足可做空校验")
    if pdt_trades_remaining is not None and pdt_trades_remaining <= 0:
        blocks.append("美股 PDT 日内交易额度不足")

    return RiskDecision(allowed=not blocks, reasons=tuple(blocks or ["风控通过"]))


def fixed_fraction_position_size(
    total_equity: float,
    last_price: float,
    fraction: float,
    lot_size: int = 1,
) -> int:
    if total_equity <= 0 or last_price <= 0 or fraction <= 0:
        return 0
    raw_quantity = int((total_equity * fraction) / last_price)
    return raw_quantity - (raw_quantity % max(lot_size, 1))


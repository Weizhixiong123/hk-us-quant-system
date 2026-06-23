from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence

from app.services.risk import evaluate_intraday_order
from quant.live.position_manager import (
    EntryStage,
    PositionPlan,
    plan_intraday_entry,
    plan_portfolio_entry,
)


class OrderGateway(Protocol):
    def send_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        price: float,
        volume: float,
        exchange: str | None = None,
    ) -> str:
        ...


@dataclass(frozen=True)
class ExecutionResult:
    submitted: bool
    symbol: str
    quantity: int
    order_id: str | None
    reasons: tuple[str, ...]


PositionSide = Literal["long", "short"]


def execute_intraday_entry(
    gateway: OrderGateway,
    symbol: str,
    price: float,
    total_equity: float,
    current_symbols: Sequence[str],
    stopped_symbols_today: Sequence[str],
    daily_loss_pct: float,
    max_daily_loss_pct: float = 3.0,
    pdt_trades_remaining: int | None = None,
    shortable: bool = True,
    is_short: bool = False,
    position_fraction_pct: float = 10.0,
    max_positions: int = 3,
    lot_size: int = 1,
    exchange: str | None = None,
) -> ExecutionResult:
    plan = plan_intraday_entry(
        symbol=symbol,
        total_equity=total_equity,
        last_price=price,
        current_symbols=current_symbols,
        stopped_symbols_today=stopped_symbols_today,
        position_fraction_pct=position_fraction_pct,
        max_positions=max_positions,
        lot_size=lot_size,
    )
    risk = evaluate_intraday_order(
        daily_loss_pct=daily_loss_pct,
        max_daily_loss_pct=max_daily_loss_pct,
        open_intraday_positions=len({_normalize_symbol(item) for item in current_symbols}),
        max_intraday_positions=max_positions,
        symbol_stopped_today=_normalize_symbol(symbol) in {_normalize_symbol(item) for item in stopped_symbols_today},
        is_short=is_short,
        shortable=shortable,
        pdt_trades_remaining=pdt_trades_remaining,
    )
    if not plan.allowed or not risk.allowed:
        return _blocked_result(plan, _merge_reasons(plan.reasons, risk.reasons))

    return _submit_entry_order(
        gateway=gateway,
        plan=plan,
        price=price,
        direction="空" if is_short else "多",
        exchange=exchange,
    )


def execute_exit_order(
    gateway: OrderGateway,
    symbol: str,
    price: float,
    quantity: int,
    side: PositionSide,
    reason: str,
    exchange: str | None = None,
) -> ExecutionResult:
    normalized_symbol = _normalize_symbol(symbol)
    if quantity <= 0:
        return ExecutionResult(
            submitted=False,
            symbol=normalized_symbol,
            quantity=0,
            order_id=None,
            reasons=("平仓数量为 0",),
        )

    try:
        order_id = gateway.send_order(
            symbol=normalized_symbol,
            direction="空" if side == "long" else "多",
            offset="平",
            price=price,
            volume=quantity,
            exchange=exchange,
        )
    except Exception as exc:
        return ExecutionResult(
            submitted=False,
            symbol=normalized_symbol,
            quantity=quantity,
            order_id=None,
            reasons=(f"下单失败：{exc}",),
        )

    return ExecutionResult(
        submitted=True,
        symbol=normalized_symbol,
        quantity=quantity,
        order_id=order_id,
        reasons=(reason,),
    )


def execute_portfolio_entry(
    gateway: OrderGateway,
    symbol: str,
    price: float,
    total_equity: float,
    current_position_values: Mapping[str, float],
    stage: EntryStage,
    pullback_confirmed: bool = False,
    single_position_cap_pct: float = 15.0,
    target_positions_max: int = 8,
    first_entry_fraction_pct: float = 60.0,
    lot_size: int = 1,
    exchange: str | None = None,
) -> ExecutionResult:
    plan = plan_portfolio_entry(
        symbol=symbol,
        total_equity=total_equity,
        last_price=price,
        current_position_values=current_position_values,
        stage=stage,
        pullback_confirmed=pullback_confirmed,
        single_position_cap_pct=single_position_cap_pct,
        target_positions_max=target_positions_max,
        first_entry_fraction=first_entry_fraction_pct / 100,
        lot_size=lot_size,
    )
    if not plan.allowed:
        return _blocked_result(plan, plan.reasons)

    return _submit_entry_order(
        gateway=gateway,
        plan=plan,
        price=price,
        direction="多",
        exchange=exchange,
    )


def _submit_entry_order(
    gateway: OrderGateway,
    plan: PositionPlan,
    price: float,
    direction: str,
    exchange: str | None,
) -> ExecutionResult:
    try:
        order_id = gateway.send_order(
            symbol=plan.symbol,
            direction=direction,
            offset="开",
            price=price,
            volume=plan.quantity,
            exchange=exchange,
        )
    except Exception as exc:
        return ExecutionResult(
            submitted=False,
            symbol=plan.symbol,
            quantity=plan.quantity,
            order_id=None,
            reasons=(f"下单失败：{exc}",),
        )

    return ExecutionResult(
        submitted=True,
        symbol=plan.symbol,
        quantity=plan.quantity,
        order_id=order_id,
        reasons=plan.reasons,
    )


def _blocked_result(plan: PositionPlan, reasons: tuple[str, ...]) -> ExecutionResult:
    return ExecutionResult(
        submitted=False,
        symbol=plan.symbol,
        quantity=0,
        order_id=None,
        reasons=reasons,
    )


def _merge_reasons(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for reason in first + second:
        if reason in {"日内仓位检查通过", "风控通过"}:
            continue
        if reason not in merged:
            merged.append(reason)
    return tuple(merged or ("执行检查通过",))


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()

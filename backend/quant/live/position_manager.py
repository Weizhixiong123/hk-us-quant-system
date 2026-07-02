from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence


EntryStage = Literal["first", "add"]


@dataclass(frozen=True)
class PositionPlan:
    allowed: bool
    symbol: str
    quantity: int
    order_value: float
    target_value: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PositionCountStatus:
    position_count: int
    target_min: int
    target_max: int
    status: Literal["under_target", "within_target", "over_target"]
    reasons: tuple[str, ...]


def plan_intraday_entry(
    symbol: str,
    total_equity: float,
    last_price: float,
    current_symbols: Sequence[str],
    stopped_symbols_today: Sequence[str],
    position_count_symbols: Sequence[str] | None = None,
    position_fraction_pct: float = 10.0,
    max_positions: int = 3,
    lot_size: int = 1,
) -> PositionPlan:
    normalized_symbol = _normalize_symbol(symbol)
    held_symbols = {_normalize_symbol(item) for item in current_symbols}
    counted_symbols = {
        _normalize_symbol(item)
        for item in (position_count_symbols if position_count_symbols is not None else current_symbols)
    }
    stopped_symbols = {_normalize_symbol(item) for item in stopped_symbols_today}
    blocks: list[str] = []

    if normalized_symbol in held_symbols:
        blocks.append("日内不重复加仓同一标的")
    if len(counted_symbols) >= max_positions:
        blocks.append("日内同时持仓数量已达上限")
    if normalized_symbol in stopped_symbols:
        blocks.append("该标的当日已止损，禁止再开仓")

    target_value = total_equity * _pct(position_fraction_pct)
    quantity = _quantity_for_value(target_value, last_price, lot_size)
    if quantity <= 0:
        blocks.append("下单数量为 0")

    return PositionPlan(
        allowed=not blocks,
        symbol=normalized_symbol,
        quantity=0 if blocks else quantity,
        order_value=0.0 if blocks else round(quantity * last_price, 2),
        target_value=round(target_value, 2),
        reasons=tuple(blocks or ["日内仓位检查通过"]),
    )


def plan_portfolio_entry(
    symbol: str,
    total_equity: float,
    last_price: float,
    current_position_values: Mapping[str, float],
    stage: EntryStage,
    pullback_confirmed: bool = False,
    single_position_cap_pct: float = 15.0,
    target_positions_max: int = 8,
    first_entry_fraction: float = 0.6,
    lot_size: int = 1,
) -> PositionPlan:
    normalized_symbol = _normalize_symbol(symbol)
    positions = {
        _normalize_symbol(item): float(value)
        for item, value in current_position_values.items()
        if float(value) > 0
    }
    current_value = positions.get(normalized_symbol, 0.0)
    full_target_value = total_equity * _pct(single_position_cap_pct)
    blocks: list[str] = []

    if stage == "first":
        if normalized_symbol in positions:
            blocks.append("中长线已有该标的持仓，首次建仓不重复加仓")
        if len(positions) >= target_positions_max:
            blocks.append("中长线持仓数量已达上限")
        target_value = full_target_value * first_entry_fraction
        order_value = target_value
    elif stage == "add":
        if normalized_symbol not in positions:
            blocks.append("补仓前必须已有该标的底仓")
        if not pullback_confirmed:
            blocks.append("回踩企稳未确认，暂不补仓")
        target_value = full_target_value
        order_value = max(full_target_value - current_value, 0.0)
        if order_value <= 0:
            blocks.append("该标的仓位已达到上限")
    else:
        raise ValueError(f"unsupported portfolio entry stage: {stage}")

    quantity = _quantity_for_value(order_value, last_price, lot_size)
    if quantity <= 0:
        blocks.append("下单数量为 0")

    return PositionPlan(
        allowed=not blocks,
        symbol=normalized_symbol,
        quantity=0 if blocks else quantity,
        order_value=0.0 if blocks else round(quantity * last_price, 2),
        target_value=round(target_value, 2),
        reasons=tuple(blocks or ["中长线仓位检查通过"]),
    )


def evaluate_portfolio_count(
    position_count: int,
    target_positions_min: int = 5,
    target_positions_max: int = 8,
) -> PositionCountStatus:
    if position_count < target_positions_min:
        return PositionCountStatus(
            position_count=position_count,
            target_min=target_positions_min,
            target_max=target_positions_max,
            status="under_target",
            reasons=("中长线持仓数量低于目标下限",),
        )
    if position_count > target_positions_max:
        return PositionCountStatus(
            position_count=position_count,
            target_min=target_positions_min,
            target_max=target_positions_max,
            status="over_target",
            reasons=("中长线持仓数量超过目标上限",),
        )
    return PositionCountStatus(
        position_count=position_count,
        target_min=target_positions_min,
        target_max=target_positions_max,
        status="within_target",
        reasons=("中长线持仓数量在目标范围内",),
    )


def _quantity_for_value(value: float, price: float, lot_size: int) -> int:
    if value <= 0 or price <= 0:
        return 0
    quantity = int(value / price)
    lot = max(lot_size, 1)
    return quantity - (quantity % lot)


def _pct(value: float) -> float:
    return max(value, 0.0) / 100


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()

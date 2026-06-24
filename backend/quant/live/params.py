from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class IntradayParams:
    stop_loss_pct: float = 1.5
    take_profit_1_pct: float = 2.0
    take_profit_2_pct: float = 3.5
    position_fraction_pct: float = 10.0
    max_positions: int = 3
    max_daily_loss_pct: float = 3.0


@dataclass(frozen=True)
class PortfolioParams:
    single_position_cap_pct: float = 15.0
    target_positions_max: int = 8
    first_entry_fraction_pct: float = 60.0
    max_symbol_drawdown_pct: float = 18.0
    take_profit_pct: float = 20.0
    rebalance_months: int = 6
    hot_gain_block_pct: float = 40.0


_INTRADAY_FIELDS = {f.name: f.type for f in fields(IntradayParams)}
_PORTFOLIO_FIELDS = {f.name: f.type for f in fields(PortfolioParams)}


class LiveParams:
    def __init__(self) -> None:
        self.intraday = IntradayParams()
        self.portfolio = PortfolioParams()

    def update(self, strategy_id: str, values: Mapping[str, Any]) -> None:
        if strategy_id == "intraday_macd":
            self.intraday = _merge(self.intraday, values, _INTRADAY_FIELDS)
        elif strategy_id == "trend_portfolio":
            self.portfolio = _merge(self.portfolio, values, _PORTFOLIO_FIELDS)


def _merge(current, values: Mapping[str, Any], known: dict[str, Any]):
    changes: dict[str, Any] = {}
    for key, value in values.items():
        if key not in known:
            continue
        changes[key] = int(value) if known[key] in ("int", int) else float(value)
    return replace(current, **changes) if changes else current

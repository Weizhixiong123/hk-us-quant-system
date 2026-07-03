from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class IntradayParams:
    fast_ema: int = 12
    slow_ema: int = 26
    signal_ema: int = 9
    stop_loss_pct: float = 1.5
    take_profit_1_pct: float = 2.0
    take_profit_2_pct: float = 3.5
    position_fraction_pct: float = 10.0
    max_positions: int = 3
    max_daily_loss_pct: float = 3.0
    # 新增:watchlist 评分参数
    score_half_life_hours: float = 4.0    # freshness 半衰期
    shortable_bonus_pts: float = 0.05    # shortable 标的 +0.05 flat bonus
    # 盘前筛选参数
    open_after_minutes: int = 30         # 开盘后 N 分钟才允许开仓
    close_before_minutes: int = 90       # 收盘前 N 分钟停止开仓
    min_turnover: float = 5_000_000.0   # 成交额下限(元)
    min_amplitude_pct: float = 2.0       # 前日振幅下限(%)
    max_amplitude_pct: float = 8.0       # 前日振幅上限(%)
    min_price: float = 2.0               # 股价下限(元)
    min_turnover_rate: float = 0.0      # 换手率下限(%)


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
            updated = _merge(self.intraday, values, _INTRADAY_FIELDS)
            _validate_intraday(updated)
            self.intraday = updated
        elif strategy_id == "trend_portfolio":
            self.portfolio = _merge(self.portfolio, values, _PORTFOLIO_FIELDS)


def _merge(current, values: Mapping[str, Any], known: dict[str, Any]):
    changes: dict[str, Any] = {}
    for key, value in values.items():
        if key not in known:
            continue
        # field.type is the string "int" under PEP 563 (from __future__ import annotations); keep both forms.
        changes[key] = int(value) if known[key] in ("int", int) else float(value)
    return replace(current, **changes) if changes else current


def _validate_intraday(params: IntradayParams) -> None:
    if not 2 <= params.fast_ema <= 60:
        raise ValueError("MACD 快线周期必须在 2 到 60 之间")
    if not 3 <= params.slow_ema <= 120:
        raise ValueError("MACD 慢线周期必须在 3 到 120 之间")
    if not 2 <= params.signal_ema <= 60:
        raise ValueError("MACD 信号线周期必须在 2 到 60 之间")
    if params.fast_ema >= params.slow_ema:
        raise ValueError("MACD 快线周期必须小于慢线周期")
    if not 0 < params.position_fraction_pct <= 100:
        raise ValueError("单次开仓仓位必须大于 0 且不超过 100%")
    if not 1 <= params.max_positions <= 20:
        raise ValueError("最大同时持仓必须在 1 到 20 之间")
    if not 0 < params.max_daily_loss_pct <= 100:
        raise ValueError("单日最大亏损必须大于 0 且不超过 100%")
    if not 0 <= params.open_after_minutes <= 240 or not 0 <= params.close_before_minutes <= 240:
        raise ValueError("开盘等待和尾盘停开时间必须在 0 到 240 分钟之间")
    if params.min_amplitude_pct > params.max_amplitude_pct:
        raise ValueError("振幅下限不能大于振幅上限")
    if params.open_after_minutes + params.close_before_minutes >= 390:
        raise ValueError("开盘等待与收盘前停止时间之和必须小于 390 分钟")
    if min(
        params.min_turnover,
        params.min_amplitude_pct,
        params.max_amplitude_pct,
        params.min_price,
        params.min_turnover_rate,
    ) < 0:
        raise ValueError("盘前筛选参数不能小于 0")

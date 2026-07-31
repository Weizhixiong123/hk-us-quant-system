from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class IntradayParams:
    fast_ema: int = 12
    slow_ema: int = 26
    signal_ema: int = 9
    slow_k_minutes: int = 15       # 大周期 K 线(分钟)
    mid_k_minutes: int = 5         # 中周期 K 线(分钟)
    fast_k_minutes: int = 3        # 小周期/触发 K 线(分钟)
    stop_loss_pct: float = 1.5
    take_profit_1_pct: float = 2.0
    take_profit_2_pct: float = 3.5
    position_fraction_pct: float = 10.0
    max_positions: int = 3
    max_daily_loss_pct: float = 3.0
    # 新增:watchlist 评分参数
    score_half_life_hours: float = 4.0    # freshness 半衰期
    shortable_bonus_pts: float = 0.05    # shortable 标的 +0.05 flat bonus
    auto_min_score: float = 0.65         # 自动选股最低评分门槛(0~1)
    # 盘前筛选参数
    open_after_minutes: int = 30         # 开盘后 N 分钟才允许开仓
    close_before_minutes: int = 90       # 收盘前 N 分钟停止开仓
    min_turnover: float = 5_000_000.0   # 成交额下限(元)
    min_amplitude_pct: float = 2.0       # 前日振幅下限(%)
    max_amplitude_pct: float = 8.0       # 前日振幅上限(%)
    min_price: float = 2.0               # 股价下限(元)
    min_turnover_rate: float = 0.0      # 换手率下限(%)
    trailing_enabled: bool = True       # 是否开启动态止盈
    trailing_start_pct: float = 2.0     # 浮盈达到 N% 后启动动态止盈
    trailing_stop_pct: float = 1.0      # 从最高点回撤 N% 后动态止盈平仓


@dataclass(frozen=True)
class PortfolioParams:
    single_position_cap_pct: float = 15.0
    target_positions_max: int = 8
    first_entry_fraction_pct: float = 60.0
    max_symbol_drawdown_pct: float = 18.0
    take_profit_pct: float = 20.0
    rebalance_months: int = 6
    hot_gain_block_pct: float = 40.0


@dataclass(frozen=True)
class MaAtrIntradayParams:
    """策略三：多周期 MA + MACD + ATR 日内参数。"""
    # === 周期设置 ===
    slow_k_minutes: int = 60        # 大周期 K 线(分钟),默认 1h
    mid_k_minutes: int = 10         # 中周期 K 线(分钟)
    fast_k_minutes: int = 5         # 小周期 K 线(分钟)

    # === 大周期 EMA ===
    slow_fast_ema: int = 3          # 大周期快线
    slow_slow_ema: int = 8          # 大周期慢线

    # === 中周期 EMA ===
    mid_fast_ema: int = 11          # 中周期快线
    mid_slow_ema: int = 30          # 中周期慢线

    # === 小周期 EMA ===
    fast_fast_ema: int = 3          # 小周期快线
    fast_slow_ema: int = 8          # 小周期慢线

    # === MACD 参数 ===
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # === ATR 参数 ===
    atr_period: int = 5             # ATR 周期
    atr_multiplier: float = 1.2     # ATR 止损倍数

    # === 止盈止损 ===
    stop_loss_pct: float = 1.5      # 固定止损(%)
    take_profit_pct: float = 3.0    # 固定止盈(%)
    trailing_enabled: bool = True
    trailing_start_pct: float = 2.0 # 动态止盈启动浮盈(%)
    trailing_stop_pct: float = 1.0  # 从最高点回撤(%)后平仓

    # === 仓位/风控 ===
    position_fraction_pct: float = 10.0
    max_positions: int = 3
    max_daily_loss_pct: float = 3.0

    # === 盘前筛选(复用策略一) ===
    open_after_minutes: int = 30
    close_before_minutes: int = 90
    min_turnover: float = 5_000_000.0
    min_amplitude_pct: float = 2.0
    max_amplitude_pct: float = 8.0
    min_price: float = 2.0
    min_turnover_rate: float = 0.0
    auto_min_score: float = 0.65
    score_half_life_hours: float = 4.0
    shortable_bonus_pts: float = 0.05


_INTRADAY_FIELDS = {f.name: f.type for f in fields(IntradayParams)}
_PORTFOLIO_FIELDS = {f.name: f.type for f in fields(PortfolioParams)}
_MA_ATR_FIELDS = {f.name: f.type for f in fields(MaAtrIntradayParams)}


class LiveParams:
    def __init__(self) -> None:
        self.intraday = IntradayParams()
        self.portfolio = PortfolioParams()
        self.ma_atr = MaAtrIntradayParams()

    def update(self, strategy_id: str, values: Mapping[str, Any]) -> None:
        if strategy_id == "intraday_macd":
            updated = _merge(self.intraday, values, _INTRADAY_FIELDS)
            _validate_intraday(updated)
            self.intraday = updated
        elif strategy_id == "trend_portfolio":
            self.portfolio = _merge(self.portfolio, values, _PORTFOLIO_FIELDS)
        elif strategy_id == "ma_atr_intraday":
            updated = _merge(self.ma_atr, values, _MA_ATR_FIELDS)
            _validate_ma_atr(updated)
            self.ma_atr = updated


def _merge(current, values: Mapping[str, Any], known: dict[str, Any]):
    changes: dict[str, Any] = {}
    for key, value in values.items():
        if key not in known:
            continue
        # field.type is the string "int" / "bool" under PEP 563 (from __future__ import annotations); keep both forms.
        if known[key] in ("bool", bool):
            changes[key] = _as_bool(value)
        else:
            changes[key] = int(value) if known[key] in ("int", int) else float(value)
    return replace(current, **changes) if changes else current


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开启"}
    return bool(value)


def _validate_intraday(params: IntradayParams) -> None:
    if not 2 <= params.fast_ema <= 60:
        raise ValueError("MACD 快线周期必须在 2 到 60 之间")
    if not 3 <= params.slow_ema <= 120:
        raise ValueError("MACD 慢线周期必须在 3 到 120 之间")
    if not 2 <= params.signal_ema <= 60:
        raise ValueError("MACD 信号线周期必须在 2 到 60 之间")
    if params.fast_ema >= params.slow_ema:
        raise ValueError("MACD 快线周期必须小于慢线周期")
    if not 1 <= params.slow_k_minutes <= 120:
        raise ValueError("大周期 K 线必须在 1 到 120 分钟之间")
    if not 1 <= params.mid_k_minutes <= 60:
        raise ValueError("中周期 K 线必须在 1 到 60 分钟之间")
    if not 1 <= params.fast_k_minutes <= 30:
        raise ValueError("小周期 K 线必须在 1 到 30 分钟之间")
    if not (params.fast_k_minutes < params.mid_k_minutes < params.slow_k_minutes):
        raise ValueError("K 线周期必须满足:小周期 < 中周期 < 大周期")
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
    if not 0 <= params.trailing_start_pct <= 100 or not 0 <= params.trailing_stop_pct <= 100:
        raise ValueError("动态止盈参数必须在 0 到 100 之间")
    if not 0 <= params.auto_min_score <= 1:
        raise ValueError("自动选股评分门槛必须在 0 到 1 之间")
    if min(
        params.min_turnover,
        params.min_amplitude_pct,
        params.max_amplitude_pct,
        params.min_price,
        params.min_turnover_rate,
    ) < 0:
        raise ValueError("盘前筛选参数不能小于 0")


def _validate_ma_atr(params: MaAtrIntradayParams) -> None:
    if params.fast_k_minutes >= params.mid_k_minutes or params.mid_k_minutes >= params.slow_k_minutes:
        raise ValueError("三周期 K 线必须满足:小周期 < 中周期 < 大周期")
    if not 2 <= params.macd_fast <= 60 or not 3 <= params.macd_slow <= 120:
        raise ValueError("MACD 周期范围无效")
    if params.macd_fast >= params.macd_slow:
        raise ValueError("MACD 快线必须小于慢线")
    if not 2 <= params.macd_signal <= 60:
        raise ValueError("MACD 信号线周期必须在 2 到 60 之间")
    if not 1 <= params.atr_period <= 60:
        raise ValueError("ATR 周期必须在 1 到 60 之间")
    if params.atr_multiplier <= 0:
        raise ValueError("ATR 止损倍数必须大于 0")
    if not 0 < params.position_fraction_pct <= 100:
        raise ValueError("单次开仓仓位必须大于 0 且不超过 100%")
    if not 1 <= params.max_positions <= 20:
        raise ValueError("最大同时持仓必须在 1 到 20 之间")
    if not 0 < params.max_daily_loss_pct <= 100:
        raise ValueError("单日最大亏损必须大于 0 且不超过 100%")
    if not 0 <= params.trailing_start_pct <= 100 or not 0 <= params.trailing_stop_pct <= 100:
        raise ValueError("动态止盈参数必须在 0 到 100 之间")

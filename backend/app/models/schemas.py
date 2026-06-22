from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Market = Literal["HK", "US"]
StrategyState = Literal["idle", "running", "paused", "blocked"]
AutomationMode = Literal["full_auto", "semi_auto"]
SignalSide = Literal["long", "short", "exit", "rebalance", "watch"]
Severity = Literal["info", "warning", "critical"]

ParamValue = int | float | str | bool


class AccountSummary(BaseModel):
    currency: str = "USD/HKD"
    total_equity: float
    cash: float
    buying_power: float
    day_pnl: float
    day_pnl_pct: float
    max_daily_loss_pct: float = 3.0


class RiskRuleStatus(BaseModel):
    code: str
    name: str
    status: Literal["pass", "watch", "blocked"]
    detail: str


class StrategyConfig(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    state: StrategyState
    automation: AutomationMode
    cadence: str
    markets: list[Market]
    params: dict[str, ParamValue]
    risk_controls: list[str]
    last_signal: str | None = None
    updated_at: datetime


class Position(BaseModel):
    symbol: str
    name: str
    market: Market
    strategy_id: str
    side: Literal["long", "short"]
    quantity: int
    avg_price: float
    last_price: float
    market_value: float
    pnl: float
    pnl_pct: float
    holding_days: int


class WatchSymbol(BaseModel):
    symbol: str
    name: str
    market: Market
    last_price: float
    change_pct: float
    turnover: float
    score: float
    tags: list[str]


class Signal(BaseModel):
    id: str
    strategy_id: str
    symbol: str
    market: Market
    side: SignalSide
    confidence: float = Field(ge=0, le=1)
    reason: str
    created_at: datetime
    status: Literal["new", "acknowledged", "executed", "filtered"]


class Order(BaseModel):
    id: str
    strategy_id: str
    symbol: str
    market: Market
    side: Literal["buy", "sell", "short", "cover"]
    quantity: int
    price: float
    status: Literal["submitted", "filled", "cancelled", "rejected"]
    created_at: datetime


class TradeLog(BaseModel):
    id: str
    time: datetime
    source: str
    severity: Severity
    message: str


class Candle(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class DashboardSnapshot(BaseModel):
    server_time: datetime
    account: AccountSummary
    risk: list[RiskRuleStatus]
    strategies: list[StrategyConfig]
    positions: list[Position]
    watchlist: list[WatchSymbol]
    signals: list[Signal]
    orders: list[Order]
    logs: list[TradeLog]
    chart: list[Candle]


class StrategyToggleRequest(BaseModel):
    enabled: bool


class StrategyParamsUpdate(BaseModel):
    params: dict[str, ParamValue]


class BacktestRequest(BaseModel):
    strategy_id: str
    market: Market
    start_date: str
    end_date: str
    symbols: list[str] = Field(default_factory=list)
    initial_capital: float = Field(default=1_000_000, gt=0)


class BacktestResult(BaseModel):
    id: str
    strategy_id: str
    market: Market
    start_date: str
    end_date: str
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    trades: int
    notes: list[str]


class StreamMessage(BaseModel):
    event: Literal["snapshot"]
    data: DashboardSnapshot


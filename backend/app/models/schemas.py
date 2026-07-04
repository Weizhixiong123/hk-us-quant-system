from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


Market = Literal["HK", "US"]
StrategyState = Literal["idle", "running", "paused", "blocked"]
AutomationMode = Literal["full_auto", "semi_auto"]
SignalSide = Literal["long", "short", "exit", "rebalance", "watch"]
Severity = Literal["info", "warning", "critical"]

ParamValue = int | float | str | bool
LiveBroker = Literal["futu", "tiger"]
FutuTradeEnv = Literal["SIMULATE", "REAL"]
TigerTradeEnv = Literal["sandbox", "live"]
IntradaySelectionMode = Literal["auto", "manual"]


class AccountSummary(BaseModel):
    currency: str = "USD/HKD"
    source: Literal["dry_run", "broker"] = "dry_run"
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
    updated_at: datetime
    triggered: bool = False
    # 评分明细(五维 + 加权和,freshness 之前)。None = 旧事件没持久化 payload
    score_breakdown: dict[str, float] | None = None
    freshness: float | None = None
    shortable: bool | None = None


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


class Trade(BaseModel):
    id: str
    order_id: str
    symbol: str
    market: Market
    side: Literal["buy", "sell", "short", "cover"]
    quantity: int
    price: float
    traded_at: datetime


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
    trades: list[Trade]
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
    symbols_mode: Literal["custom", "auto"] = "custom"
    initial_capital: float = Field(default=1_000_000, gt=0)
    params_snapshot: dict[str, ParamValue] = Field(default_factory=dict)
    symbols_source: str = "request"


class EquityPoint(BaseModel):
    time: str
    equity: float
    drawdown_pct: float


class BacktestTradeRow(BaseModel):
    symbol: str
    market: Market
    side: Literal["long", "short"] = "long"
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    position_size: float
    quantity: float
    pnl: float
    pnl_pct: float
    position_source: str = "strategy_param"
    symbols_source: str = "request"
    entry_reason: str = ""
    exit_reason: str = ""
    max_favorable_pct: float = 0.0
    max_adverse_pct: float = 0.0


class BacktestResult(BaseModel):
    id: str
    strategy_id: str
    market: Market
    start_date: str
    end_date: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    trades: int
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    trade_rows: list[BacktestTradeRow] = Field(default_factory=list)
    notes: list[str]


class StreamMessage(BaseModel):
    event: Literal["snapshot"]
    data: DashboardSnapshot


class LiveRuntimeSettings(BaseModel):
    enabled: bool = False
    dry_run: bool = True
    broker: LiveBroker = "futu"
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    default_equity: float = Field(default=1_000_000, gt=0)


class FutuLiveSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=11111, gt=0)
    trd_env: FutuTradeEnv = "SIMULATE"
    market: Market = "HK"
    markets: list[Market] = Field(default_factory=lambda: ["HK", "US"])
    real_trading_confirmed: bool = False


class TigerLiveSettings(BaseModel):
    tiger_id: str = ""
    account: str = ""
    private_key: str | None = None
    private_key_path: str = ""
    tiger_public_key_path: str = ""
    environment: TigerTradeEnv = "sandbox"
    language: str = "zh_CN"
    max_contracts: int = Field(default=100, ge=1)
    use_preset_contracts: bool = False
    market: Market = "US"
    markets: list[Market] = Field(default_factory=lambda: ["US"])
    live_trading_confirmed: bool = False
    clear_private_key: bool = False


class PublicTigerLiveSettings(BaseModel):
    tiger_id: str = ""
    account: str = ""
    private_key_path: str = ""
    tiger_public_key_path: str = ""
    private_key_configured: bool = False
    environment: TigerTradeEnv = "sandbox"
    language: str = "zh_CN"
    max_contracts: int = 100
    use_preset_contracts: bool = False
    market: Market = "US"
    markets: list[Market] = Field(default_factory=lambda: ["US"])
    live_trading_confirmed: bool = False


class LiveSafetySettings(BaseModel):
    operator_note: str = ""


class ManualSymbol(BaseModel):
    symbol: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    name: str = Field(default="", max_length=64)
    market: Market
    shortable: bool = False


class IntradayParamsSettings(BaseModel):
    fast_ema: int = Field(default=12, ge=2, le=60)
    slow_ema: int = Field(default=26, ge=3, le=120)
    signal_ema: int = Field(default=9, ge=2, le=60)
    position_fraction_pct: float = Field(default=10.0, gt=0, le=100)
    max_positions: int = Field(default=3, ge=1, le=20)
    max_daily_loss_pct: float = Field(default=3.0, gt=0, le=100)
    open_after_minutes: int = Field(default=30, ge=0, le=240, description="开盘后多少分钟开始允许开仓")
    close_before_minutes: int = Field(default=90, ge=0, le=240, description="收盘前多少分钟停止开仓")
    min_turnover: float = Field(default=5_000_000.0, ge=0, description="日均成交额下限(元)")
    min_amplitude_pct: float = Field(default=2.0, ge=0, le=100, description="前日振幅下限(%)")
    max_amplitude_pct: float = Field(default=8.0, ge=0, le=100, description="前日振幅上限(%)")
    min_price: float = Field(default=2.0, ge=0, description="股价下限(元)")
    min_turnover_rate: float = Field(default=0.0, ge=0, le=100, description="换手率下限(%)")
    trailing_enabled: bool = True
    trailing_start_pct: float = Field(default=2.0, ge=0, le=100, description="动态止盈启动浮盈(%)")
    trailing_stop_pct: float = Field(default=1.0, ge=0, le=100, description="动态止盈回撤(%)")


class SymbolNameLookup(BaseModel):
    symbol: str
    market: Market
    name: str | None = None


class IntradayUniverseSettings(BaseModel):
    selection_mode: IntradaySelectionMode = "auto"
    manual_symbols: list[ManualSymbol] = Field(default_factory=list, max_length=100)


class LiveSettingsUpdate(BaseModel):
    runtime: LiveRuntimeSettings | None = None
    futu: FutuLiveSettings | None = None
    tiger: TigerLiveSettings | None = None
    safety: LiveSafetySettings | None = None
    intraday_universe: IntradayUniverseSettings | None = None
    intraday_params: IntradayParamsSettings | None = None


class LiveSettingsSnapshot(BaseModel):
    runtime: LiveRuntimeSettings
    futu: FutuLiveSettings
    tiger: PublicTigerLiveSettings
    safety: LiveSafetySettings
    intraday_universe: IntradayUniverseSettings
    intraday_params: IntradayParamsSettings
    saved_at: datetime
    restart_required: bool = True


class RuntimeReloadResult(BaseModel):
    ok: bool
    error: str | None = None
    runtime_running: bool
    runtime_enabled: bool
    runtime_dry_run: bool
    runtime_broker: str


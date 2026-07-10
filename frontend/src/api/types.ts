export type Market = "HK" | "US";
export type StrategyState = "idle" | "running" | "paused" | "blocked";
export type AutomationMode = "full_auto" | "semi_auto";
export type ParamValue = string | number | boolean;
export type LiveBroker = "futu" | "tiger";
export type FutuTradeEnv = "SIMULATE" | "REAL";
export type TigerTradeEnv = "sandbox" | "live";

export interface AccountSummary {
  currency: string;
  source: "dry_run" | "broker";
  total_equity: number;
  cash: number;
  buying_power: number;
  day_pnl: number;
  day_pnl_pct: number;
  max_daily_loss_pct: number;
}

export interface RiskRuleStatus {
  code: string;
  name: string;
  status: "pass" | "watch" | "blocked";
  detail: string;
}

export interface StrategyConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  state: StrategyState;
  automation: AutomationMode;
  cadence: string;
  markets: Market[];
  params: Record<string, ParamValue>;
  risk_controls: string[];
  last_signal: string | null;
  updated_at: string;
}

export interface Position {
  symbol: string;
  name: string;
  market: Market;
  strategy_id: string;
  side: "long" | "short";
  quantity: number;
  avg_price: number;
  last_price: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  holding_days: number;
}

export interface WatchSymbol {
  symbol: string;
  name: string;
  market: Market;
  strategy_id: string;
  last_price: number;
  change_pct: number;
  turnover: number;
  score: number;
  tags: string[];
  updated_at: string;
  triggered: boolean;
  // 新增(后端 score_for_symbol 输出):五维明细 / freshness / shortable bonus
  score_breakdown: Record<string, number> | null;
  freshness: number | null;
  shortable: boolean | null;
}

export interface Signal {
  id: string;
  strategy_id: string;
  symbol: string;
  market: Market;
  side: "long" | "short" | "exit" | "rebalance" | "watch";
  confidence: number;
  reason: string;
  created_at: string;
  status: "new" | "acknowledged" | "executed" | "filtered";
}

export interface Order {
  id: string;
  strategy_id: string;
  symbol: string;
  market: Market;
  side: "buy" | "sell" | "short" | "cover";
  quantity: number;
  price: number;
  status: "submitted" | "filled" | "cancelled" | "rejected";
  created_at: string;
}

export interface Trade {
  id: string;
  order_id: string;
  symbol: string;
  market: Market;
  side: "buy" | "sell" | "short" | "cover";
  quantity: number;
  price: number;
  traded_at: string;
}

export interface TradeLog {
  id: string;
  time: string;
  source: string;
  severity: "info" | "warning" | "critical";
  message: string;
}

export interface CloseUnassignedPositionsResult {
  submitted: number;
  results: {
    symbol: string;
    submitted: boolean;
    quantity: number;
    order_id: string | null;
    reasons: string[];
  }[];
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface DashboardSnapshot {
  server_time: string;
  account: AccountSummary;
  risk: RiskRuleStatus[];
  strategies: StrategyConfig[];
  positions: Position[];
  watchlist: WatchSymbol[];
  signals: Signal[];
  orders: Order[];
  trades: Trade[];
  logs: TradeLog[];
  chart: Candle[];
}

export interface BacktestRequest {
  strategy_id: string;
  market: Market;
  start_date: string;
  end_date: string;
  symbols: string[];
  symbols_mode?: "custom" | "auto";
  initial_capital: number;
  symbols_source?: string;
  params_snapshot?: Record<string, ParamValue>;
}

export interface EquityPoint {
  time: string;
  equity: number;
  drawdown_pct: number;
}

export interface BacktestTradeRow {
  symbol: string;
  market: Market;
  side: "long" | "short";
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  position_size: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  position_source: string;
  symbols_source: string;
  entry_reason: string;
  exit_reason: string;
  action: string;
  action_label: string;
  cash_after: number;
  position_value: number;
  weight_pct: number;
  max_favorable_pct: number;
  max_adverse_pct: number;
}

export interface BacktestResult {
  id: string;
  strategy_id: string;
  market: Market;
  start_date: string;
  end_date: string;
  created_at: string;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  win_rate_pct: number;
  trades: number;
  equity_curve: EquityPoint[];
  trade_rows: BacktestTradeRow[];
  notes: string[];
}

export interface LiveRuntimeSettings {
  enabled: boolean;
  dry_run: boolean;
  broker: LiveBroker;
  poll_interval_seconds: number;
  default_equity: number;
}

export interface FutuLiveSettings {
  host: string;
  port: number;
  trd_env: FutuTradeEnv;
  market: Market;
  markets: Market[];
  real_trading_confirmed: boolean;
}

export interface TigerLiveSettings {
  tiger_id: string;
  account: string;
  private_key_path: string;
  tiger_public_key_path: string;
  private_key_configured?: boolean;
  environment: TigerTradeEnv;
  language: string;
  max_contracts: number;
  use_preset_contracts: boolean;
  market: Market;
  markets: Market[];
  live_trading_confirmed: boolean;
}

export interface LiveSafetySettings {
  operator_note: string;
}

export interface ManualSymbol {
  symbol: string;
  name: string;
  market: Market;
  shortable: boolean;
}

export interface SymbolNameLookup {
  symbol: string;
  market: Market;
  name: string | null;
}

export interface IntradayUniverseSettings {
  selection_mode: "auto" | "manual";
  manual_symbols: ManualSymbol[];
}

export interface IntradayParamsSettings {
  fast_ema: number;
  slow_ema: number;
  signal_ema: number;
  slow_k_minutes: number;
  mid_k_minutes: number;
  fast_k_minutes: number;
  position_fraction_pct: number;
  max_positions: number;
  max_daily_loss_pct: number;
  open_after_minutes: number;
  close_before_minutes: number;
  min_turnover: number;
  min_amplitude_pct: number;
  max_amplitude_pct: number;
  min_price: number;
  min_turnover_rate: number;
  trailing_enabled: boolean;
  trailing_start_pct: number;
  trailing_stop_pct: number;
  auto_min_score: number;
  max_auto_candidates: number;
}

export interface LiveSettingsSnapshot {
  runtime: LiveRuntimeSettings;
  futu: FutuLiveSettings;
  tiger: TigerLiveSettings;
  safety: LiveSafetySettings;
  intraday_universe: IntradayUniverseSettings;
  intraday_params: IntradayParamsSettings;
  saved_at: string;
  restart_required: boolean;
}

export interface LiveSettingsUpdate {
  runtime?: Partial<LiveRuntimeSettings>;
  futu?: Partial<FutuLiveSettings>;
  tiger?: Partial<TigerLiveSettings> & {
    private_key?: string;
    clear_private_key?: boolean;
  };
  safety?: Partial<LiveSafetySettings>;
  intraday_universe?: IntradayUniverseSettings;
  intraday_params?: IntradayParamsSettings;
}

export interface RuntimeReloadResult {
  ok: boolean;
  error: string | null;
  runtime_running: boolean;
  runtime_enabled: boolean;
  runtime_dry_run: boolean;
  runtime_broker: string;
}


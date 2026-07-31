<script setup lang="ts">
import { computed, onMounted, ref, watch, type Component } from "vue";
import {
  Activity,
  ChevronRight,
  ChevronsLeft,
  ClipboardList,
  Database,
  FileText,
  Home,
  LayoutDashboard,
  LineChart,
  ListChecks,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Star,
  WalletCards
} from "lucide-vue-next";
import LiveSettingsPanel from "./components/LiveSettingsPanel.vue";
import ManualUniversePanel from "./components/ManualUniversePanel.vue";
import PositionManagement from "./components/PositionManagement.vue";
import StrategyCard from "./components/StrategyCard.vue";
import { fetchTradeHistory } from "./api/client";
import { useDashboard } from "./composables/useDashboard";
import type { AccountSummary, Market, RiskRuleStatus, Signal, Trade, TradeLog } from "./api/types";

type ViewName = "dashboard" | "strategies" | "candidates" | "positions" | "trades" | "logs" | "settings";
type QueryStatus = "triggered" | "selected" | "watching" | "pending" | "closed";

interface NavItem {
  label: string;
  icon: Component;
  view?: ViewName;
}

interface QueryRow {
  symbol: string;
  name: string;
  market: Market;
  strategy: string;
  strategyDetail: string;
  sourceLabel: string;
  sourceDetail: string;
  status: QueryStatus;
  statusLabel: string;
  reason: string;
  score: number;
  updatedAt: string;
  starred: boolean;
  scoreBreakdown: Record<string, number> | null;
  freshness: number | null;
  scoreTooltip: string;
}

interface ExecutionRow {
  id: string;
  time: string;
  symbol: string;
  side: string;
  price: number;
  status: string;
}

interface EventRow {
  id: string;
  at: string;
  time: string;
  type: string;
  content: string;
  severity: "info" | "warning" | "critical";
}

const {
  account,
  accounts,
  backtest,
  backtestError,
  backtestProgress,
  backtestProgressLabel,
  backtestRunning,
  dashboard,
  error,
  load,
  loading,
  logs,
  orders,
  positions,
  risk,
  runBacktest,
  saveParam,
  signals,
  strategies,
  streamState,
  toggleStrategy,
  trades,
  watchlist
} = useDashboard();

const activeView = ref<ViewName>("dashboard");
const selectedStrategyId = ref<string | null>(null);

function selectStrategy(strategy: { id: string; name: string }) {
  selectedStrategyId.value = strategy.id;
}

const tradeHistory = ref<Trade[]>([]);

async function loadTradeHistory(): Promise<void> {
  try {
    tradeHistory.value = await fetchTradeHistory();
  } catch {
    tradeHistory.value = [];
  }
}

async function refreshDashboard(): Promise<void> {
  await load();
}

watch(activeView, (view) => {
  if (view === "dashboard" || view === "trades") {
    loadTradeHistory();
  }
});

onMounted(() => {
  loadTradeHistory();
});

const navItems: NavItem[] = [
  { label: "控制台", icon: Home, view: "dashboard" },
  { label: "实盘配置", icon: Settings2, view: "settings" },
  { label: "策略管理", icon: ClipboardList, view: "strategies" },
  { label: "候选股票", icon: ListChecks, view: "candidates" },
  { label: "持仓风控", icon: ShieldCheck, view: "positions" },
  { label: "成交记录", icon: Database, view: "trades" },
  { label: "运行日志", icon: FileText, view: "logs" }
];

const appYear = new Date().getFullYear();
const appVersion = "1.0.0";
const weekdayIndexes: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6
};

const streamLabel = computed(() => {
  switch (streamState.value) {
    case "live":
      return "实时流";
    case "connecting":
      return "连接中";
    case "offline":
      return "离线";
  }
});

const accountSourceLabel = computed(() => {
  if (!account.value) {
    return "--";
  }
  return account.value.source === "dry_run" ? "干跑资金" : "券商账户";
});

const currentModeLabel = computed(() => {
  if (!account.value) {
    return "--";
  }
  return account.value.source === "dry_run" ? "干跑" : "券商账户";
});

const queriedStocks = computed<QueryRow[]>(() =>
  watchlist.value.map((item, index) => {
    const tags = item.tags;
    const reason = tags.length > 0 ? tags.join(" / ") : "等待信号";
    const source = querySourceFromTags(tags, reason);
    const strategy = {
      intraday_macd: { label: "策略一", detail: "日内 MACD" },
      trend_portfolio: { label: "策略二", detail: "中长线选股" },
      ma_atr_intraday: { label: "策略三", detail: "多周期 MA + MACD + ATR" }
    }[item.strategy_id] ?? { label: "策略一", detail: "日内 MACD" };
    const status = resolveQueryStatus(reason, item.market, item.triggered);
    const bd = item.score_breakdown;
    const fresh = item.freshness ?? 1;
    const tooltip = bd
      ? `候选评分 ${item.score.toFixed(2)} · consistency ${bd.consistency.toFixed(2)} · volume ${bd.volume_ratio.toFixed(2)} · atr ${bd.atr_quality.toFixed(2)} · trend ${bd.trend_filter.toFixed(2)} · liquidity ${bd.liquidity_rank.toFixed(2)}${bd.weighted !== undefined ? ` · 加权 ${bd.weighted.toFixed(2)}` : ""} · freshness ${fresh.toFixed(2)}${item.shortable ? " · 可做空 +0.05" : ""}`
      : `score ${item.score} (无明细,旧事件)`;

    return {
      symbol: item.symbol,
      name: item.name,
      market: item.market,
      strategy: strategy.label,
      strategyDetail: strategy.detail,
      sourceLabel: source.label,
      sourceDetail: source.detail,
      status,
      statusLabel: queryStatusLabel(status),
      reason,
      score: Math.round(item.score * 100),
      scoreBreakdown: bd,
      freshness: item.freshness,
      scoreTooltip: tooltip,
      updatedAt: time(item.updated_at),
      starred: index === 2
    };
  })
);

type QueryTabKey = "all" | "intraday" | "trend" | "maAtr" | "triggered" | "watching";

const queryTabDefs: { key: QueryTabKey; label: string; match: (item: QueryRow) => boolean }[] = [
  { key: "all", label: "全部", match: () => true },
  { key: "intraday", label: "策略一 · 日内 MACD", match: (item) => item.strategy === "策略一" },
  { key: "trend", label: "策略二 · 中长线选股", match: (item) => item.strategy === "策略二" },
  { key: "maAtr", label: "策略三 · MA + MACD + ATR", match: (item) => item.strategy === "策略三" },
  { key: "watching", label: "观察中", match: (item) => item.status === "watching" },
  { key: "triggered", label: "信号触发", match: (item) => item.status === "triggered" }
];

const activeQueryTab = ref<QueryTabKey>("all");
const showAllQueriedStocks = ref(false);

const queryTabs = computed(() =>
  queryTabDefs.map((def) => ({
    key: def.key,
    label: def.label,
    count: queriedStocks.value.filter(def.match).length
  }))
);

const filteredQueriedStocks = computed(() => {
  const def = queryTabDefs.find((tab) => tab.key === activeQueryTab.value) ?? queryTabDefs[0];
  return queriedStocks.value.filter(def.match);
});

const visibleQueriedStocks = computed(() =>
  showAllQueriedStocks.value
    ? filteredQueriedStocks.value
    : filteredQueriedStocks.value.slice(0, 6)
);

watch(activeQueryTab, () => {
  showAllQueriedStocks.value = false;
});

const activePositions = computed(() => positions.value.slice(0, 4));

const totalPositionValue = computed(() =>
  positions.value.reduce((total, position) => total + position.market_value, 0)
);

const recentExecutions = computed<ExecutionRow[]>(() => {
  const recentTrades = new Map<string, Trade>();
  [...trades.value, ...tradeHistory.value].forEach((trade) => {
    recentTrades.set(trade.id, trade);
  });
  const sortedTrades = [...recentTrades.values()]
    .sort((left, right) => Date.parse(right.traded_at) - Date.parse(left.traded_at))
    .slice(0, 4);

  if (sortedTrades.length > 0) {
    return sortedTrades.map((trade) => ({
      id: trade.id,
      time: timeOnly(trade.traded_at),
      symbol: trade.symbol,
      side: sideLabel(trade.side),
      price: trade.price,
      status: "已成交"
    }));
  }

  return orders.value.slice(0, 4).map((order) => ({
    id: order.id,
    time: timeOnly(order.created_at),
    symbol: order.symbol,
    side: sideLabel(order.side),
    price: order.price,
    status: orderStatusLabel(order.status)
  }));
});

const eventRows = computed<EventRow[]>(() => {
  const logRows = logs.value.map((log) => eventFromLog(log));
  const signalRows = signals.value.map((signal) => eventFromSignal(signal));

  return [...logRows, ...signalRows]
    .sort((left, right) => new Date(right.at).getTime() - new Date(left.at).getTime())
    .slice(0, 4);
});

const runtimeLogRows = computed<EventRow[]>(() =>
  logs.value
    .map((log) => eventFromLog(log))
    .sort((left, right) => new Date(right.at).getTime() - new Date(left.at).getTime())
);

const orderLogCount = computed(() =>
  runtimeLogRows.value.filter((item) => ["委托", "下单", "撤单"].some((word) => item.content.includes(word))).length
);

const alertLogCount = computed(() =>
  runtimeLogRows.value.filter((item) => item.severity !== "info").length
);

const riskRows = computed(() => risk.value.slice(0, 5));

const riskPassCount = computed(() => risk.value.filter((item) => item.status === "pass").length);

const triggeredCount = computed(() => queriedStocks.value.filter((item) => item.status === "triggered").length);

const selectedStrategy = computed(() =>
  strategies.value.find((strategy) => strategy.id === selectedStrategyId.value) ?? strategies.value[0] ?? null
);

const enabledStrategyCount = computed(() => strategies.value.filter((strategy) => strategy.enabled).length);

const strategyMarketCoverage = computed(() => {
  const markets = new Set<Market>();
  strategies.value.forEach((strategy) => strategy.markets.forEach((market) => markets.add(market)));
  return ["HK", "US"].filter((market) => markets.has(market as Market)).join(" / ") || "--";
});

const todayStrategySignals = computed(() => {
  const today = dashboard.value?.server_time?.slice(0, 10) ?? new Date().toISOString().slice(0, 10);
  return signals.value.filter((signal) => signal.created_at.slice(0, 10) === today).length;
});

watch(
  strategies,
  (items) => {
    if (items.length === 0) {
      selectedStrategyId.value = null;
      return;
    }
    if (!selectedStrategyId.value || !items.some((strategy) => strategy.id === selectedStrategyId.value)) {
      selectedStrategyId.value = items.find((strategy) => strategy.enabled)?.id ?? items[0].id;
    }
  },
  { immediate: true }
);

const displayedAccounts = computed(() =>
  accounts.value.length > 0 ? accounts.value : account.value ? [account.value] : []
);

function accountLabel(item: AccountSummary): string {
  if (item.source === "dry_run") return "干跑账户";
  if (item.market === "HK") return "港股模拟账户";
  if (item.market === "US") return "美股模拟账户";
  return "券商账户";
}

function dailyLossUsed(item: AccountSummary): number {
  if (item.max_daily_loss_pct <= 0 || item.day_pnl_pct >= 0) {
    return 0;
  }
  return Math.min(100, (-item.day_pnl_pct / item.max_daily_loss_pct) * 100);
}

function switchView(view?: ViewName): void {
  if (view) {
    activeView.value = view;
  }
}

function isTrendCandidate(reason: string): boolean {
  return ["周线", "月线", "日线", "候选持仓", "中长线"].some((keyword) => reason.includes(keyword));
}

function querySourceFromTags(tags: string[], reason: string): { label: string; detail: string } {
  if (tags.includes("手动+筛选")) {
    return { label: "手动+筛选", detail: "手动加入 + 自动筛选" };
  }
  if (tags.includes("手动选股")) {
    return { label: "手动", detail: "手动加入候选池" };
  }
  if (tags.includes("盘前筛选")) {
    return { label: "筛选", detail: "自动筛选入池" };
  }
  if (tags.includes("月末选股") || isTrendCandidate(reason)) {
    return { label: "月末选股", detail: "中长线候选池" };
  }
  return { label: "候选", detail: "策略候选池" };
}

function resolveQueryStatus(reason: string, market: Market, triggered: boolean): QueryStatus {
  if (triggered) {
    return "triggered";
  }
  if (!isMarketOpenNow(market)) {
    return "closed";
  }
  if (reason.includes("金叉") || reason.includes("已触发")) {
    return "triggered";
  }
  if (reason.includes("候选持仓") || reason.includes("入选")) {
    return "selected";
  }
  if (reason.includes("观察") || reason.includes("等待")) {
    return "watching";
  }
  return "pending";
}

function queryStatusLabel(status: QueryStatus): string {
  switch (status) {
    case "triggered":
      return "信号触发";
    case "selected":
      return "已入选";
    case "watching":
      return "观察中";
    case "pending":
      return "未触发";
    case "closed":
      return "已闭市";
  }
}

function isMarketOpenNow(market: Market): boolean {
  const serverTime = dashboard.value?.server_time;
  const value = serverTime ? new Date(serverTime) : new Date();
  const local = marketLocalParts(value, market);

  if (local.weekday === 0 || local.weekday === 6) {
    return false;
  }

  const minutes = local.hour * 60 + local.minute;
  if (market === "HK") {
    return (minutes >= 570 && minutes < 720) || (minutes >= 780 && minutes < 960);
  }
  return minutes >= 570 && minutes < 960;
}

function marketLocalParts(value: Date, market: Market): { weekday: number; hour: number; minute: number } {
  const timezone = market === "US" ? "America/New_York" : "Asia/Hong_Kong";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(value);
  const partMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));

  return {
    weekday: weekdayIndexes[partMap.weekday] ?? 0,
    hour: Number(partMap.hour ?? 0),
    minute: Number(partMap.minute ?? 0)
  };
}

function money(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0
  }).format(value);
}

function pct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toneClass(value: number): "gain" | "loss" {
  return value >= 0 ? "gain" : "loss";
}

function sideTone(side: string): "gain" | "loss" {
  return side === "卖出" || side === "做空" ? "loss" : "gain";
}

function statusClass(status: QueryStatus): string {
  return `status-${status}`;
}

function riskStatusLabel(status: RiskRuleStatus["status"]): string {
  switch (status) {
    case "pass":
      return "正常";
    case "watch":
      return "观察";
    case "blocked":
      return "阻断";
  }
}

function riskStatusTextClass(status: RiskRuleStatus["status"]): "gain" | "loss" | "watch-text" {
  if (status === "pass") {
    return "gain";
  }
  return status === "blocked" ? "loss" : "watch-text";
}

function sideLabel(side: string): string {
  switch (side) {
    case "buy":
      return "买入";
    case "sell":
      return "卖出";
    case "short":
      return "做空";
    case "cover":
      return "平空";
    default:
      return side;
  }
}

function orderStatusLabel(status: string): string {
  switch (status) {
    case "submitted":
      return "已提交";
    case "filled":
      return "已成交";
    case "cancelled":
      return "已撤销";
    case "rejected":
      return "已拒绝";
    default:
      return status;
  }
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  gateway: "连接",
  risk: "风控",
  intraday_macd: "策略一",
  trend_portfolio: "策略二",
  ma_atr_intraday: "策略三",
  position_risk: "持仓风控",
  runtime: "运行时",
  broker: "券商",
  dry_run: "干跑",
  backtest: "回测",
  system: "系统"
};

function eventTypeLabel(type: string): string {
  if (type === "FUTU_HK") return "富途·港股";
  if (type === "FUTU_US") return "富途·美股";
  return EVENT_TYPE_LABELS[type] ?? type;
}

function eventFromLog(log: TradeLog): EventRow {
  return {
    id: log.id,
    at: log.time,
    time: timeOnly(log.time),
    type: log.source,
    content: log.message,
    severity: log.severity
  };
}

function eventFromSignal(signal: Signal): EventRow {
  return {
    id: signal.id,
    at: signal.created_at,
    time: timeOnly(signal.created_at),
    type: "策略",
    content: `${signal.symbol} · ${signal.reason}`,
    severity: signal.status === "filtered" ? "warning" : "info"
  };
}

function time(value?: string): string {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function timeOnly(value?: string): string {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function logTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}
</script>

<template>
  <main class="ops-shell">
    <header class="ops-topbar">
      <div class="ops-brand">
        <div class="mark">
          <LineChart :size="22" />
        </div>
        <div>
          <h1>港美股双策略量化系统</h1>
          <p>HK / US DUAL STRATEGY QUANT SYSTEM</p>
        </div>
      </div>

      <div class="ops-top-actions">
        <div class="top-nav" aria-label="工作区切换">
          <button
            type="button"
            :class="{ active: activeView === 'dashboard' }"
            @click="activeView = 'dashboard'"
          >
            <LayoutDashboard :size="18" />
            <span>控制台</span>
          </button>
          <button
            type="button"
            :class="{ active: activeView === 'settings' }"
            @click="activeView = 'settings'"
          >
            <Settings2 :size="18" />
            <span>实盘配置</span>
          </button>
        </div>
        <div class="stream-pill" :class="streamState">
          <Radio :size="15" />
          <span>{{ streamLabel }}</span>
        </div>
        <div class="server-clock">
          <strong>{{ time(dashboard?.server_time) }}</strong>
          <span>服务器时间 (UTC+8)</span>
        </div>
        <button class="icon-button" title="刷新" :disabled="loading" @click="load">
          <RefreshCw :size="18" />
        </button>
      </div>
    </header>

    <p v-if="error" class="error-bar">{{ error }}</p>

    <div class="ops-body">
      <aside class="ops-sidebar">
        <nav class="side-menu" aria-label="主菜单">
          <button
            v-for="item in navItems"
            :key="item.label"
            type="button"
            :class="{ active: item.view === activeView }"
            :disabled="!item.view"
            @click="switchView(item.view)"
          >
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </button>
        </nav>

        <section class="side-status">
          <div>
            <span>当前模式</span>
            <strong>{{ currentModeLabel }}</strong>
          </div>
          <div>
            <span>账户来源</span>
            <strong>{{ accountSourceLabel }}</strong>
          </div>
          <div>
            <span>轮询状态</span>
            <strong>{{ streamLabel }}</strong>
          </div>
          <div>
            <span>最近刷新</span>
            <strong>{{ time(dashboard?.server_time) }}</strong>
          </div>
        </section>

        <button class="collapse-button" type="button">
          <ChevronsLeft :size="18" />
          <span>收起菜单</span>
        </button>
      </aside>

      <section class="ops-content">
        <template v-if="activeView === 'dashboard'">
          <section v-if="account" class="ops-account-overview" :class="{ single: displayedAccounts.length === 1 }">
            <article v-for="item in displayedAccounts" :key="item.market ?? item.account_id" class="account-summary-card">
              <header>
                <div class="metric-icon">
                  <WalletCards :size="24" />
                </div>
                <div>
                  <strong>{{ accountLabel(item) }}</strong>
                  <small>{{ item.account_id ? `账户 ${item.account_id}` : accountSourceLabel }}</small>
                </div>
                <span class="account-currency">{{ item.currency }}</span>
              </header>
              <div class="account-metric-row">
                <div>
                  <span>总权益</span>
                  <strong>{{ money(item.total_equity) }}</strong>
                </div>
                <div>
                  <span>可用现金</span>
                  <strong>{{ money(item.cash) }}</strong>
                </div>
                <div>
                  <span>当日盈亏</span>
                  <strong :class="toneClass(item.day_pnl)">{{ money(item.day_pnl) }}</strong>
                  <small :class="toneClass(item.day_pnl)">{{ pct(item.day_pnl_pct) }}</small>
                </div>
              </div>
            </article>
            <article class="metric-card">
              <div class="metric-icon danger">
                <ShieldCheck :size="26" />
              </div>
              <div>
                <span>最大日亏损</span>
                <strong class="loss">{{ account.max_daily_loss_pct.toFixed(1) }}%</strong>
                <small>触发后停止交易</small>
              </div>
              <p>风控阈值</p>
            </article>
            <article class="metric-card">
              <div class="metric-icon">
                <Database :size="26" />
              </div>
              <div v-if="dashboard?.history_kline_quota">
                <span>历史 K 线额度</span>
                <strong>{{ dashboard.history_kline_quota.used }}/{{ dashboard.history_kline_quota.total }}</strong>
                <small>
                  今日自动 {{ dashboard.history_kline_quota.daily_new_used }}/{{ dashboard.history_kline_quota.daily_new_limit }}
                  · 全部新增 {{ dashboard.history_kline_quota.daily_total_new }}
                </small>
              </div>
              <div v-else>
                <span>历史 K 线额度</span>
                <strong>--/--</strong>
                <small>等待富途连接后查询</small>
              </div>
              <p v-if="dashboard?.history_kline_quota">
                剩余 {{ dashboard.history_kline_quota.remaining }} · 预留 {{ dashboard.history_kline_quota.reserve }}
                <template v-if="dashboard.history_kline_quota.next_release_date">
                  · {{ dashboard.history_kline_quota.next_release_date.slice(5) }}
                  预计释放 {{ dashboard.history_kline_quota.next_release_count }}
                </template>
              </p>
              <p v-else>尚未获取</p>
            </article>
          </section>

          <section class="ops-dashboard-grid">
            <div class="ops-main-column">
              <ManualUniversePanel @saved="refreshDashboard" />
              <article class="query-panel">
              <header class="query-head">
                <div>
                  <h2>今日候选池</h2>
                  <p>手动加入和自动筛选统一进入候选池</p>
                </div>
                <button class="text-button" type="button" :disabled="loading" @click="load">
                  <RefreshCw :size="16" />
                  <span>刷新</span>
                </button>
              </header>

              <div class="query-tabs">
                <button
                  v-for="tab in queryTabs"
                  :key="tab.key"
                  type="button"
                  :class="{ active: tab.key === activeQueryTab }"
                  @click="activeQueryTab = tab.key"
                >
                  <span>{{ tab.label }}</span>
                  <strong>{{ tab.count }}</strong>
                </button>
              </div>

              <div class="query-table-wrap" :class="{ expanded: showAllQueriedStocks }">
                <table class="query-table">
                  <thead>
                    <tr>
                      <th>股票代码</th>
                      <th>名称</th>
                      <th>市场</th>
                      <th>来源</th>
                      <th>状态</th>
                      <th>信号原因</th>
                      <th>评分</th>
                      <th>更新时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in visibleQueriedStocks" :key="item.symbol">
                      <td>
                        <div class="query-symbol">
                          <Star class="favorite" :class="{ filled: item.starred }" :size="17" />
                          <strong>{{ item.symbol }}</strong>
                        </div>
                      </td>
                      <td>{{ item.name }}</td>
                      <td>
                        <span class="market-pill" :class="item.market.toLowerCase()">{{ item.market }}</span>
                      </td>
                      <td>
                        <strong class="strategy-label">{{ item.sourceLabel }}</strong>
                        <small>{{ item.sourceDetail }}</small>
                      </td>
                      <td>
                        <span class="query-status" :class="statusClass(item.status)">
                          {{ item.statusLabel }}
                        </span>
                      </td>
                      <td class="reason-cell">{{ item.reason }}</td>
                      <td>
                        <div class="score-cell" :title="item.scoreTooltip">
                          <strong>{{ item.score }}</strong>
                          <span class="score-track">
                            <i :style="{ width: `${item.score}%` }" />
                          </span>
                        </div>
                      </td>
                      <td>{{ item.updatedAt }}</td>
                    </tr>
                    <tr v-if="visibleQueriedStocks.length === 0">
                      <td class="empty-row" colspan="8">暂无候选股票</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <footer class="query-foot">
                <button
                  class="link-button"
                  type="button"
                  @click="activeView = 'candidates'"
                >
                  查看全部 {{ filteredQueriedStocks.length }} 只股票
                  <ChevronRight :size="16" />
                </button>
                <span>闭市时保留各市场最近一次候选结果</span>
              </footer>
            </article>

              <section class="ops-bottom-grid">
            <article class="summary-panel">
              <header class="summary-head clickable" @click="activeView = 'positions'">
                <div>
                  <h3>持仓 ({{ positions.length }})</h3>
                  <p>总市值 {{ money(totalPositionValue) }} USD/HKD</p>
                </div>
                <ChevronRight :size="17" />
              </header>
              <div class="mini-table-wrap">
                <table class="mini-table">
                  <thead>
                    <tr>
                      <th>代码</th>
                      <th>名称</th>
                      <th>方向</th>
                      <th>市值</th>
                      <th>盈亏(%)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="position in activePositions" :key="position.symbol">
                      <td>{{ position.symbol }}</td>
                      <td>{{ position.name }}</td>
                      <td :class="position.side === 'long' ? 'gain' : 'loss'">
                        {{ position.side === "long" ? "多" : "空" }}
                      </td>
                      <td>{{ money(position.market_value) }}</td>
                      <td :class="toneClass(position.pnl_pct)">{{ pct(position.pnl_pct) }}</td>
                    </tr>
                    <tr v-if="activePositions.length === 0">
                      <td class="empty-row" colspan="5">暂无持仓</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>

            <article class="summary-panel">
              <header class="summary-head clickable" @click="activeView = 'trades'">
                <div>
                  <h3>最近成交</h3>
                  <p>成交回报，不等于当前持仓数</p>
                </div>
                <ChevronRight :size="17" />
              </header>
              <div class="mini-table-wrap">
                <table class="mini-table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>代码</th>
                      <th>方向</th>
                      <th>价格</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="execution in recentExecutions" :key="execution.id">
                      <td>{{ execution.time }}</td>
                      <td>{{ execution.symbol }}</td>
                      <td :class="sideTone(execution.side)">{{ execution.side }}</td>
                      <td>{{ execution.price.toFixed(2) }}</td>
                      <td>
                        <span class="filled-chip">{{ execution.status }}</span>
                      </td>
                    </tr>
                    <tr v-if="recentExecutions.length === 0">
                      <td class="empty-row" colspan="5">暂无成交</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>

            <article class="summary-panel">
              <header class="summary-head">
                <div>
                  <h3>交易事件</h3>
                  <p>策略、风控、连接事件</p>
                </div>
                <ChevronRight :size="17" />
              </header>
              <div class="event-list compact">
                <article v-for="event in eventRows" :key="event.id" :class="event.severity">
                  <time>{{ event.time }}</time>
                  <strong>{{ eventTypeLabel(event.type) }}</strong>
                  <span>{{ event.content }}</span>
                </article>
                <p v-if="eventRows.length === 0" class="empty-inline">暂无事件</p>
              </div>
            </article>
              </section>
            </div>

            <aside class="ops-right-rail">
              <section class="rail-card">
                <header class="rail-card-head">
                  <div>
                    <h3>风控闸门</h3>
                    <p>券商连接与交易阈值</p>
                  </div>
                  <span class="state-pill">正常</span>
                </header>

                <div class="risk-mini-list">
                  <article v-for="item in riskRows" :key="item.code" class="risk-mini-row">
                    <div>
                      <strong>{{ item.name }}</strong>
                      <small>{{ item.detail }}</small>
                    </div>
                    <span :class="riskStatusTextClass(item.status)">
                      {{ riskStatusLabel(item.status) }}
                    </span>
                  </article>
                </div>

                <div v-for="item in displayedAccounts" :key="`risk-${item.market ?? item.account_id}`" class="risk-meter">
                  <div>
                    <span>{{ accountLabel(item) }}日亏损</span>
                    <strong>{{ item.max_daily_loss_pct.toFixed(1) }}%</strong>
                  </div>
                  <span class="meter-track danger">
                    <i :style="{ width: `${dailyLossUsed(item)}%` }" />
                  </span>
                  <small>已用 {{ dailyLossUsed(item).toFixed(1) }}%</small>
                </div>

                <button class="rail-link" type="button">
                  风控规则详情
                  <ChevronRight :size="16" />
                </button>
              </section>

              <section class="rail-card">
                <header class="rail-card-head">
                  <div>
                    <h3>运行状态</h3>
                    <p>后台引擎与数据流</p>
                  </div>
                  <span class="state-pill live">运行中</span>
                </header>

                <div class="runtime-list">
                  <article>
                    <span>运行引擎</span>
                    <strong>LiveRuntime</strong>
                    <small :class="streamState === 'offline' ? 'loss' : 'gain'">{{ streamLabel }}</small>
                  </article>
                  <article>
                    <span>当前模式</span>
                    <strong>{{ currentModeLabel }}</strong>
                    <small>{{ accountSourceLabel }}</small>
                  </article>
                  <article>
                    <span>通过风控</span>
                    <strong>{{ riskPassCount }} / {{ risk.length }}</strong>
                    <small>规则检查</small>
                  </article>
                  <article>
                    <span>最近心跳</span>
                    <strong>{{ time(dashboard?.server_time) }}</strong>
                    <small>服务器时间</small>
                  </article>
                </div>

                <button class="rail-link" type="button" @click="activeView = 'logs'">
                  查看运行日志
                  <ChevronRight :size="16" />
                </button>
              </section>
            </aside>
          </section>
        </template>

        <section v-else-if="activeView === 'strategies'" class="strategy-management-view">
          <header class="strategy-command-head">
            <div class="strategy-command-copy">
              <p class="eyebrow">STRATEGY CONTROL</p>
              <h2>策略管理</h2>
              <p>调整策略参数与执行参数，并查看由代码驱动的交易记录。</p>
            </div>
            <div class="strategy-command-stats">
              <article>
                <LineChart :size="24" />
                <span><strong>{{ enabledStrategyCount }}</strong>运行中</span>
              </article>
              <article>
                <ClipboardList :size="24" />
                <span><strong>{{ strategies.length }}</strong>策略总数</span>
              </article>
              <article>
                <Radio :size="24" />
                <span><strong>{{ strategyMarketCoverage }}</strong>港美市场</span>
              </article>
              <article>
                <Activity :size="24" />
                <span><strong>{{ todayStrategySignals }}</strong>今日信号</span>
              </article>
            </div>
          </header>

          <section class="strategy-switch-section" aria-label="策略切换区">
            <div class="strategy-switch-title">
              <strong>策略配置</strong>
              <span>点击卡片仅查看配置，不会改变运行状态</span>
            </div>
            <div class="strategy-switchboard">
              <button
                v-for="(strategy, index) in strategies"
                :key="strategy.id"
                class="strategy-switch-card"
                :class="{ selected: selectedStrategy?.id === strategy.id, muted: !strategy.enabled }"
                type="button"
                :aria-label="`查看策略${index + 1}：${strategy.name}配置，不改变运行状态`"
                @click="selectStrategy(strategy)"
              >
                <span class="strategy-select-dot" />
                <span class="strategy-switch-icon">
                  <LineChart v-if="strategy.id === 'intraday_macd'" :size="26" />
                  <ShieldCheck v-else-if="!strategy.enabled" :size="26" />
                  <Activity v-else :size="26" />
                </span>
                <span class="strategy-switch-body">
                  <span class="strategy-switch-topline">
                    <strong>策略{{ index + 1 }}：{{ strategy.name }}</strong>
                    <em :class="{ running: strategy.enabled }">{{ strategy.enabled ? '运行中' : '未启用' }}</em>
                  </span>
                  <span class="strategy-switch-meta">
                    <b>{{ strategy.automation === 'full_auto' ? '全自动交易' : '选股 + 持仓' }}</b>
                    <i />
                    <b>{{ strategy.markets.join(' / ') }}</b>
                    <i />
                    <b>{{ strategy.cadence }}</b>
                  </span>
                  <span class="strategy-switch-facts">
                    <span><small>今日信号</small><strong>{{ signals.filter((signal) => signal.strategy_id === strategy.id).length }}</strong></span>
                    <span><small>{{ strategy.id === 'intraday_macd' ? '今日开仓' : '持仓数量' }}</small><strong>{{ positions.filter((position) => position.strategy_id === strategy.id).length }}</strong></span>
                    <span class="switch-actions"><b>查看配置</b><em>{{ strategy.enabled ? '运行中' : '未启用' }}</em></span>
                  </span>
                </span>
              </button>
            </div>
          </section>

          <StrategyCard
            v-if="selectedStrategy"
            :strategy="selectedStrategy"
            :backtest="backtest"
            :backtest-running="backtestRunning"
            :backtest-progress="backtestProgress"
            :backtest-progress-label="backtestProgressLabel"
            :backtest-error="backtestError"
            @toggle="toggleStrategy"
            @update-param="saveParam"
            @backtest="runBacktest"
          />
        </section>

        <section v-else-if="activeView === 'candidates'" class="candidates-view">
          <header class="strategy-page-head">
            <div>
              <p class="eyebrow">CANDIDATE UNIVERSE</p>
              <h2>候选股票</h2>
              <p>手动加入和自动筛选汇总成统一候选池，可按策略与状态过滤。</p>
            </div>
            <div class="strategy-page-summary">
              <span><strong>{{ queriedStocks.length }}</strong>只股票</span>
              <span><strong>{{ filteredQueriedStocks.length }}</strong>当前筛选</span>
              <span><strong>{{ triggeredCount }}</strong>已触发</span>
            </div>
          </header>

          <article class="query-panel">
            <header class="query-head">
              <div>
                <h2>全部候选池</h2>
                <p>闭市时保留各市场最近一次候选结果</p>
              </div>
              <button class="text-button" type="button" :disabled="loading" @click="load">
                <RefreshCw :size="16" />
                <span>刷新</span>
              </button>
            </header>

            <div class="query-tabs">
              <button
                v-for="tab in queryTabs"
                :key="tab.key"
                type="button"
                :class="{ active: tab.key === activeQueryTab }"
                @click="activeQueryTab = tab.key"
              >
                <span>{{ tab.label }}</span>
                <strong>{{ tab.count }}</strong>
              </button>
            </div>

            <div class="query-table-wrap expanded">
              <table class="query-table">
                <thead>
                  <tr>
                    <th>股票代码</th>
                    <th>名称</th>
                    <th>市场</th>
                    <th>来源策略</th>
                    <th>状态</th>
                    <th>信号原因</th>
                    <th>评分</th>
                    <th>更新时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in filteredQueriedStocks" :key="item.symbol">
                    <td>
                      <div class="query-symbol">
                        <Star class="favorite" :class="{ filled: item.starred }" :size="17" />
                        <strong>{{ item.symbol }}</strong>
                      </div>
                    </td>
                    <td>{{ item.name }}</td>
                    <td>
                      <span class="market-pill" :class="item.market.toLowerCase()">{{ item.market }}</span>
                    </td>
                    <td>
                      <strong class="strategy-label">{{ item.strategy }}</strong>
                      <small>{{ item.strategyDetail }}</small>
                    </td>
                    <td>
                      <span class="query-status" :class="statusClass(item.status)">
                        {{ item.statusLabel }}
                      </span>
                    </td>
                    <td class="reason-cell">{{ item.reason }}</td>
                    <td>
                      <div class="score-cell" :title="item.scoreTooltip">
                        <strong>{{ item.score }}</strong>
                        <span class="score-track">
                          <i :style="{ width: `${item.score}%` }" />
                        </span>
                      </div>
                    </td>
                    <td>{{ item.updatedAt }}</td>
                  </tr>
                  <tr v-if="filteredQueriedStocks.length === 0">
                    <td class="empty-row" colspan="8">暂无候选股票</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>

        <PositionManagement
          v-else-if="activeView === 'positions'"
          :account="account"
          :orders="orders"
          :positions="positions"
          :strategies="strategies"
          :loading="loading"
          @refresh="load"
        />

        <section v-else-if="activeView === 'trades'" class="trades-view">
          <article class="query-panel">
            <header class="query-head">
              <div>
                <h2>成交记录</h2>
                <p>当前模式：{{ currentModeLabel }} · 共 {{ tradeHistory.length }} 笔（不同模式互相隔离）</p>
              </div>
              <button class="text-button" type="button" @click="loadTradeHistory">
                <RefreshCw :size="16" />
                <span>刷新</span>
              </button>
            </header>
            <div class="query-table-wrap">
              <table class="query-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>代码</th>
                    <th>市场</th>
                    <th>方向</th>
                    <th>价格</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in tradeHistory" :key="item.id">
                    <td>{{ time(item.traded_at) }}</td>
                    <td><strong>{{ item.symbol }}</strong></td>
                    <td>
                      <span class="market-pill" :class="item.market.toLowerCase()">{{ item.market }}</span>
                    </td>
                    <td :class="sideTone(sideLabel(item.side))">{{ sideLabel(item.side) }}</td>
                    <td>{{ item.price.toFixed(2) }}</td>
                    <td>{{ item.quantity }}</td>
                  </tr>
                  <tr v-if="tradeHistory.length === 0">
                    <td class="empty-row" colspan="6">暂无成交记录</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>

        <section v-else-if="activeView === 'logs'" class="logs-view">
          <header class="strategy-page-head log-page-head">
            <div>
              <p class="eyebrow">RUNTIME LEDGER</p>
              <h2>运行日志</h2>
              <p>汇总策略、风控与券商回报，富途开单和拒单会在这里实时出现。</p>
            </div>
            <button class="text-button" type="button" :disabled="loading" @click="load">
              <RefreshCw :size="16" />
              <span>刷新日志</span>
            </button>
          </header>

          <div class="log-metrics">
            <article>
              <span>当前记录</span>
              <strong>{{ runtimeLogRows.length }}</strong>
              <small>实时日志</small>
            </article>
            <article>
              <span>委托事件</span>
              <strong>{{ orderLogCount }}</strong>
              <small>下单 / 撤单</small>
            </article>
            <article :class="{ attention: alertLogCount > 0 }">
              <span>异常与警告</span>
              <strong>{{ alertLogCount }}</strong>
              <small>需要关注</small>
            </article>
          </div>

          <article class="query-panel runtime-log-panel">
            <header class="runtime-log-head">
              <div>
                <span class="live-dot" />
                <strong>实时事件流</strong>
              </div>
              <small>{{ streamLabel }} · {{ currentModeLabel }}</small>
            </header>
            <div class="runtime-log-list">
              <article
                v-for="item in runtimeLogRows"
                :key="item.id"
                class="runtime-log-row"
                :class="item.severity"
              >
                <time>{{ logTime(item.at) }}</time>
                <span class="log-source">{{ eventTypeLabel(item.type) }}</span>
                <span class="log-severity">{{ item.severity === 'info' ? '信息' : item.severity === 'warning' ? '警告' : '异常' }}</span>
                <p>{{ item.content }}</p>
              </article>
              <p v-if="runtimeLogRows.length === 0" class="empty-inline">暂无运行日志</p>
            </div>
          </article>
        </section>

        <LiveSettingsPanel v-else />
      </section>
    </div>

    <footer class="ops-footer">
      <span class="ops-footer-copy">© {{ appYear }} 港美股双策略量化系统 · 版本 {{ appVersion }}</span>
      <span class="ops-footer-status" :class="error ? 'is-down' : 'is-up'">
        <span>服务状态</span>
        <i></i>
        <strong>{{ error ? "异常" : "正常运行" }}</strong>
      </span>
    </footer>

  </main>
</template>

<style scoped>
/* ===== 候选池表格重新设计 ===== */

/* --- 表头 --- */
.query-table thead th {
  padding: 10px 12px;
  background: rgba(247, 248, 245, 0.95);
  color: var(--faint);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

/* --- 表体行 --- */
.query-table tbody td {
  padding: 10px 12px;
  font-size: 13px;
  border-color: rgba(24, 32, 31, 0.06);
}

.query-table tbody tr:last-child td {
  border-bottom: none;
}

/* --- 股票代码 --- */
.query-symbol strong {
  font-size: 13px;
  font-weight: 700;
}

/* --- 来源(策略标识) --- */
.strategy-label {
  font-size: 12px;
  font-weight: 700;
}

.strategy-label + small {
  display: block;
  margin-top: 2px;
  color: var(--faint);
  font-size: 10px;
}

/* --- 状态标识:色点 + 胶囊 --- */
.query-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.query-status::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-triggered {
  color: #16805d;
  background: rgba(22, 128, 93, 0.08);
}
.status-triggered::before { background: #16805d; }

.status-watching {
  color: #d56a17;
  background: rgba(213, 106, 23, 0.08);
}
.status-watching::before { background: #d56a17; }

.status-closed {
  color: var(--muted);
  background: rgba(101, 112, 110, 0.08);
}
.status-closed::before { background: var(--muted); }

/* --- 评分单元格 --- */
.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 80px;
}

.score-cell strong {
  min-width: 24px;
  font-size: 13px;
  font-weight: 700;
  text-align: right;
}

.score-track {
  flex: 1;
  height: 4px;
  border-radius: 999px;
  background: rgba(24, 32, 31, 0.08);
}

.score-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--accent);
}

/* --- 信号原因单元格 --- */
.reason-cell {
  max-width: 280px;
  color: var(--ink);
  font-size: 12.5px;
  line-height: 1.4;
  white-space: normal;
}

/* --- 市场标识 --- */
.market-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.market-pill.hk {
  color: #0d6f65;
  background: rgba(13, 111, 101, 0.08);
}

.market-pill.us {
  color: #1d4d7c;
  background: rgba(29, 77, 124, 0.08);
}

/* --- 空行 --- */
.empty-row {
  padding: 28px 12px !important;
  text-align: center;
  color: var(--faint);
  font-size: 13px;
}
</style>

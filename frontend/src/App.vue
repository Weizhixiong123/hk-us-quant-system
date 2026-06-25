<script setup lang="ts">
import { computed, ref, type Component } from "vue";
import {
  Activity,
  Briefcase,
  ChevronRight,
  ChevronsLeft,
  ClipboardList,
  Database,
  FileText,
  Home,
  LayoutDashboard,
  LineChart,
  ListChecks,
  Package,
  Radio,
  ReceiptText,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Star,
  WalletCards
} from "lucide-vue-next";
import LiveSettingsPanel from "./components/LiveSettingsPanel.vue";
import { useDashboard } from "./composables/useDashboard";
import type { Market, RiskRuleStatus, Signal, TradeLog } from "./api/types";

type ViewName = "dashboard" | "settings";
type QueryStatus = "triggered" | "selected" | "watching" | "pending";

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
  status: QueryStatus;
  statusLabel: string;
  reason: string;
  score: number;
  updatedAt: string;
  starred: boolean;
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
  dashboard,
  error,
  load,
  loading,
  logs,
  orders,
  positions,
  risk,
  signals,
  streamState,
  trades,
  watchlist
} = useDashboard();

const activeView = ref<ViewName>("dashboard");

const navItems: NavItem[] = [
  { label: "控制台", icon: Home, view: "dashboard" },
  { label: "实盘配置", icon: Settings2, view: "settings" },
  { label: "策略管理", icon: ClipboardList },
  { label: "候选股票", icon: ListChecks },
  { label: "持仓管理", icon: Package },
  { label: "订单管理", icon: ReceiptText },
  { label: "成交记录", icon: Database },
  { label: "风控中心", icon: ShieldCheck },
  { label: "运行日志", icon: FileText }
];

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
  return account.value.source === "dry_run" ? "Dry-run 资金" : "券商账户";
});

const buyingPowerLabel = computed(() => {
  if (!account.value) {
    return "购买力 --";
  }
  const label = account.value.source === "dry_run" ? "模拟购买力" : "券商购买力";
  return `${label} ${money(account.value.buying_power)}`;
});

const currentModeLabel = computed(() => {
  if (!account.value) {
    return "--";
  }
  return account.value.source === "dry_run" ? "Dry-run" : "券商账户";
});

const queriedStocks = computed<QueryRow[]>(() =>
  watchlist.value.map((item, index) => {
    const reason = item.tags.length > 0 ? item.tags.join(" / ") : "等待信号";
    const strategyTwo = isTrendCandidate(reason);
    const status = resolveQueryStatus(reason);

    return {
      symbol: item.symbol,
      name: item.name,
      market: item.market,
      strategy: strategyTwo ? "策略二" : "策略一",
      strategyDetail: strategyTwo ? "中长线选股" : "日内 MACD",
      status,
      statusLabel: queryStatusLabel(status),
      reason,
      score: Math.round(item.score * 100),
      updatedAt: time(dashboard.value?.server_time),
      starred: index === 2
    };
  })
);

const queryTabs = computed(() => [
  { label: "全部", count: queriedStocks.value.length, active: true },
  { label: "策略一 · 日内 MACD", count: queriedStocks.value.filter((item) => item.strategy === "策略一").length },
  { label: "策略二 · 中长线选股", count: queriedStocks.value.filter((item) => item.strategy === "策略二").length },
  { label: "已触发", count: queriedStocks.value.filter((item) => item.status === "triggered").length },
  { label: "观察中", count: queriedStocks.value.filter((item) => item.status === "watching").length }
]);

const visibleQueriedStocks = computed(() => queriedStocks.value.slice(0, 6));

const activePositions = computed(() => positions.value.slice(0, 4));

const totalPositionValue = computed(() =>
  positions.value.reduce((total, position) => total + position.market_value, 0)
);

const recentExecutions = computed<ExecutionRow[]>(() => {
  if (trades.value.length > 0) {
    return trades.value.slice(0, 4).map((trade) => ({
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

const riskRows = computed(() => risk.value.slice(0, 5));

const riskPassCount = computed(() => risk.value.filter((item) => item.status === "pass").length);

const maxDailyLossUsed = computed(() => {
  if (!account.value || account.value.max_daily_loss_pct <= 0) {
    return 0;
  }
  return Math.min(100, (Math.abs(account.value.day_pnl_pct) / account.value.max_daily_loss_pct) * 100);
});

function switchView(view?: ViewName): void {
  if (view) {
    activeView.value = view;
  }
}

function isTrendCandidate(reason: string): boolean {
  return ["周线", "月线", "日线", "候选持仓", "中长线"].some((keyword) => reason.includes(keyword));
}

function resolveQueryStatus(reason: string): QueryStatus {
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
      return "已触发";
    case "selected":
      return "已入选";
    case "watching":
      return "观察中";
    case "pending":
      return "未触发";
  }
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
          <section v-if="account" class="ops-metric-grid">
            <article class="metric-card">
              <div class="metric-icon">
                <WalletCards :size="26" />
              </div>
              <div>
                <span>总权益</span>
                <strong>{{ money(account.total_equity) }}</strong>
                <small>{{ account.currency }}</small>
              </div>
              <p>{{ accountSourceLabel }}</p>
            </article>
            <article class="metric-card">
              <div class="metric-icon">
                <Briefcase :size="26" />
              </div>
              <div>
                <span>可用现金</span>
                <strong>{{ money(account.cash) }}</strong>
                <small>{{ account.currency }}</small>
              </div>
              <p>{{ buyingPowerLabel }}</p>
            </article>
            <article class="metric-card">
              <div class="metric-icon">
                <Activity :size="26" />
              </div>
              <div>
                <span>当日盈亏</span>
                <strong :class="toneClass(account.day_pnl)">{{ money(account.day_pnl) }}</strong>
                <small :class="toneClass(account.day_pnl)">{{ pct(account.day_pnl_pct) }}</small>
              </div>
              <p>{{ currentModeLabel }} 模式</p>
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
          </section>

          <section class="ops-dashboard-grid">
            <div class="ops-main-column">
              <article class="query-panel">
              <header class="query-head">
                <div>
                  <h2>今日查询股票</h2>
                  <p>每日 08:30 执行筛选</p>
                </div>
                <button class="text-button" type="button" :disabled="loading" @click="load">
                  <RefreshCw :size="16" />
                  <span>刷新</span>
                </button>
              </header>

              <div class="query-tabs">
                <button
                  v-for="tab in queryTabs"
                  :key="tab.label"
                  type="button"
                  :class="{ active: tab.active }"
                >
                  <span>{{ tab.label }}</span>
                  <strong>{{ tab.count }}</strong>
                </button>
              </div>

              <div class="query-table-wrap">
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
                        <div class="score-cell">
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
                <button class="link-button" type="button">
                  查看全部 {{ queriedStocks.length }} 只股票
                  <ChevronRight :size="16" />
                </button>
                <span>数据每 5 分钟自动更新</span>
              </footer>
            </article>

              <section class="ops-bottom-grid">
            <article class="summary-panel">
              <header class="summary-head">
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
              <header class="summary-head">
                <div>
                  <h3>最近成交</h3>
                  <p>订单与成交回报</p>
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
                  <strong>{{ event.type }}</strong>
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

                <div class="risk-meter">
                  <div>
                    <span>单日亏损阈值</span>
                    <strong>{{ account?.max_daily_loss_pct.toFixed(1) ?? "--" }}%</strong>
                  </div>
                  <span class="meter-track danger">
                    <i :style="{ width: `${maxDailyLossUsed}%` }" />
                  </span>
                  <small>已用 {{ Math.min(maxDailyLossUsed, 100).toFixed(1) }}%</small>
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

                <button class="rail-link" type="button">
                  查看运行日志
                  <ChevronRight :size="16" />
                </button>
              </section>
            </aside>
          </section>
        </template>

        <LiveSettingsPanel v-else />
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed } from "vue";
import {
  Activity,
  Database,
  LineChart,
  ListChecks,
  Radio,
  RefreshCw,
  ShieldCheck
} from "lucide-vue-next";
import EventFeed from "./components/EventFeed.vue";
import MarketChart from "./components/MarketChart.vue";
import PositionsTable from "./components/PositionsTable.vue";
import StrategyCard from "./components/StrategyCard.vue";
import { useDashboard } from "./composables/useDashboard";
import type { EquityPoint } from "./api/types";

const {
  account,
  backtest,
  backtests,
  chart,
  dashboard,
  error,
  load,
  loading,
  logs,
  positions,
  risk,
  runBacktest,
  saveParam,
  selectBacktest,
  signals,
  strategies,
  streamState,
  toggleStrategy,
  watchlist
} = useDashboard();

const selectedEquity = computed(() => {
  const curve = backtest.value?.equity_curve ?? [];
  if (curve.length === 0) {
    return null;
  }
  return curve[curve.length - 1].equity;
});

const equityPolyline = computed(() => buildEquityPolyline(backtest.value?.equity_curve ?? []));

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

function buildEquityPolyline(curve: EquityPoint[]): string {
  if (curve.length < 2) {
    return "";
  }

  const values = curve.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return curve
    .map((point, index) => {
      const x = (index / (curve.length - 1)) * 100;
      const y = 36 - ((point.equity - min) / range) * 32 - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function money(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0
  }).format(value);
}

function pct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function strategyName(strategyId: string): string {
  return strategies.value.find((strategy) => strategy.id === strategyId)?.name ?? strategyId;
}

function toneClass(value: number): "gain" | "loss" {
  return value >= 0 ? "gain" : "loss";
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
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="mark">
          <LineChart :size="22" />
        </div>
        <div>
          <p class="eyebrow">HK / US QUANT OPS</p>
          <h1>港美股双策略量化系统</h1>
        </div>
      </div>

      <div class="top-actions">
        <div class="stream-pill" :class="streamState">
          <Radio :size="15" />
          <span>{{ streamLabel }}</span>
        </div>
        <span class="server-time">{{ time(dashboard?.server_time) }}</span>
        <button class="icon-button" title="刷新" :disabled="loading" @click="load">
          <RefreshCw :size="18" />
        </button>
      </div>
    </header>

    <p v-if="error" class="error-bar">{{ error }}</p>

    <section v-if="account" class="metric-strip">
      <article>
        <span>总权益</span>
        <strong>{{ money(account.total_equity) }}</strong>
        <small>{{ account.currency }}</small>
      </article>
      <article>
        <span>可用现金</span>
        <strong>{{ money(account.cash) }}</strong>
        <small>购买力 {{ money(account.buying_power) }}</small>
      </article>
      <article>
        <span>当日盈亏</span>
        <strong :class="toneClass(account.day_pnl)">{{ money(account.day_pnl) }}</strong>
        <small :class="toneClass(account.day_pnl)">{{ pct(account.day_pnl_pct) }}</small>
      </article>
      <article>
        <span>最大日亏损</span>
        <strong>{{ account.max_daily_loss_pct.toFixed(1) }}%</strong>
        <small>触发后停止交易</small>
      </article>
    </section>

    <section class="strategy-grid">
      <StrategyCard
        v-for="strategy in strategies"
        :key="strategy.id"
        :strategy="strategy"
        @toggle="toggleStrategy"
        @update-param="saveParam"
        @backtest="runBacktest"
      />
    </section>

    <section class="workspace-grid">
      <article class="panel chart-panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">AAPL · 5min</p>
            <h2>行情与信号结构</h2>
          </div>
          <Activity :size="19" />
        </header>
        <MarketChart :candles="chart" />
      </article>

      <aside class="panel risk-panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">RISK</p>
            <h2>风控闸门</h2>
          </div>
          <ShieldCheck :size="19" />
        </header>
        <div class="risk-list">
          <article v-for="item in risk" :key="item.code" :class="item.status">
            <strong>{{ item.name }}</strong>
            <span>{{ item.detail }}</span>
          </article>
        </div>
      </aside>
    </section>

    <section class="lower-grid">
      <article class="panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">POSITIONS</p>
            <h2>持仓</h2>
          </div>
          <Database :size="19" />
        </header>
        <PositionsTable :positions="positions" />
      </article>

      <article class="panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">WATCHLIST</p>
            <h2>候选池</h2>
          </div>
          <ListChecks :size="19" />
        </header>
        <div class="watch-grid">
          <article v-for="item in watchlist" :key="item.symbol" class="watch-row">
            <div>
              <strong>{{ item.symbol }}</strong>
              <small>{{ item.name }} · {{ item.market }}</small>
            </div>
            <span :class="toneClass(item.change_pct)">{{ pct(item.change_pct) }}</span>
            <meter min="0" max="1" :value="item.score" />
            <p>{{ item.tags.join(" / ") }}</p>
          </article>
        </div>
      </article>
    </section>

    <section class="lower-grid tail-grid">
      <article class="panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">SIGNALS / LOGS</p>
            <h2>交易事件</h2>
          </div>
          <Activity :size="19" />
        </header>
        <EventFeed :signals="signals" :logs="logs" />
      </article>

      <article class="panel backtest-panel">
        <header class="panel-title">
          <div>
            <p class="eyebrow">BACKTEST</p>
            <h2>最近回测</h2>
          </div>
          <LineChart :size="19" />
        </header>
        <div v-if="backtest" class="backtest-result">
          <div class="backtest-heading">
            <strong>{{ backtest.id }} · {{ backtest.market }}</strong>
            <span>{{ time(backtest.created_at) }}</span>
          </div>
          <dl>
            <div>
              <dt>收益</dt>
              <dd>{{ pct(backtest.total_return_pct) }}</dd>
            </div>
            <div>
              <dt>回撤</dt>
              <dd>{{ backtest.max_drawdown_pct.toFixed(2) }}%</dd>
            </div>
            <div>
              <dt>Sharpe</dt>
              <dd>{{ backtest.sharpe.toFixed(2) }}</dd>
            </div>
            <div>
              <dt>胜率</dt>
              <dd>{{ backtest.win_rate_pct.toFixed(2) }}%</dd>
            </div>
          </dl>
          <div v-if="equityPolyline" class="equity-sparkline">
            <svg viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
              <polyline :points="equityPolyline" />
            </svg>
            <span v-if="selectedEquity !== null">资金 {{ money(selectedEquity) }}</span>
          </div>
          <p v-for="note in backtest.notes" :key="note">{{ note }}</p>
          <div v-if="backtests.length" class="backtest-history">
            <button
              v-for="item in backtests"
              :key="item.id"
              type="button"
              class="history-row"
              :class="{ active: backtest.id === item.id }"
              @click="selectBacktest(item)"
            >
              <span>{{ strategyName(item.strategy_id) }}</span>
              <strong :class="toneClass(item.total_return_pct)">{{ pct(item.total_return_pct) }}</strong>
              <small>{{ item.market }} · {{ time(item.created_at) }}</small>
            </button>
          </div>
        </div>
        <div v-else class="empty-state">
          <strong>等待回测任务</strong>
          <span>点击任一策略卡片的回测按钮生成结果。</span>
        </div>
      </article>
    </section>
  </main>
</template>


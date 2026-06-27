<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Layers3,
  PieChart,
  RefreshCw,
  ShieldCheck,
  WalletCards
} from "lucide-vue-next";
import type { AccountSummary, Position, StrategyConfig } from "../api/types";

type PositionFilter = "all" | "intraday" | "trend";
type PositionRisk = "pass" | "watch" | "blocked";

interface PositionRow extends Position {
  strategyLabel: string;
  strategyDetail: string;
  weightPct: number;
  risk: PositionRisk;
  riskLabel: string;
}

const props = defineProps<{
  account: AccountSummary | null;
  positions: Position[];
  strategies: StrategyConfig[];
  loading: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
}>();

const activeFilter = ref<PositionFilter>("all");

const totalMarketValue = computed(() =>
  props.positions.reduce((total, position) => total + position.market_value, 0)
);

const totalPnl = computed(() =>
  props.positions.reduce((total, position) => total + position.pnl, 0)
);

const totalCost = computed(() =>
  props.positions.reduce(
    (total, position) => total + Math.max(0, position.market_value - position.pnl),
    0
  )
);

const totalPnlPct = computed(() =>
  totalCost.value > 0 ? (totalPnl.value / totalCost.value) * 100 : 0
);

const utilizationPct = computed(() => {
  const equity = props.account?.total_equity ?? 0;
  return equity > 0 ? (totalMarketValue.value / equity) * 100 : 0;
});

const positionRows = computed<PositionRow[]>(() =>
  props.positions.map((position) => {
    const risk = positionRisk(position);
    return {
      ...position,
      strategyLabel: strategyLabel(position.strategy_id),
      strategyDetail: strategyDetail(position.strategy_id),
      weightPct: positionWeight(position),
      risk,
      riskLabel: riskLabel(risk)
    };
  })
);

const filteredRows = computed(() => {
  if (activeFilter.value === "intraday") {
    return positionRows.value.filter((position) => position.strategy_id === "intraday_macd");
  }
  if (activeFilter.value === "trend") {
    return positionRows.value.filter((position) => position.strategy_id === "trend_portfolio");
  }
  return positionRows.value;
});

const filterTabs = computed(() => [
  { key: "all" as const, label: "全部持仓", count: props.positions.length },
  {
    key: "intraday" as const,
    label: "策略一 · 日内",
    count: props.positions.filter((position) => position.strategy_id === "intraday_macd").length
  },
  {
    key: "trend" as const,
    label: "策略二 · 中长线",
    count: props.positions.filter((position) => position.strategy_id === "trend_portfolio").length
  }
]);

const allocationRows = computed(() =>
  [...positionRows.value].sort((left, right) => right.market_value - left.market_value)
);

const riskCounts = computed(() => ({
  pass: positionRows.value.filter((position) => position.risk === "pass").length,
  watch: positionRows.value.filter((position) => position.risk === "watch").length,
  blocked: positionRows.value.filter((position) => position.risk === "blocked").length
}));

function strategyParam(strategyId: string, key: string, fallback: number): number {
  const strategy = props.strategies.find((item) => item.id === strategyId);
  const value = strategy?.params[key];
  return typeof value === "number" ? value : fallback;
}

function positionWeight(position: Position): number {
  const equity = props.account?.total_equity ?? 0;
  return equity > 0 ? (position.market_value / equity) * 100 : 0;
}

function positionRisk(position: Position): PositionRisk {
  const weight = positionWeight(position);
  const intraday = position.strategy_id === "intraday_macd";
  const positionCap = intraday
    ? strategyParam("intraday_macd", "position_fraction_pct", 10)
    : strategyParam("trend_portfolio", "single_position_cap_pct", 15);
  const lossLimit = intraday
    ? strategyParam("intraday_macd", "stop_loss_pct", 1.5)
    : strategyParam("trend_portfolio", "max_symbol_drawdown_pct", 18);

  if ((intraday && position.holding_days > 0) || weight > positionCap || position.pnl_pct <= -lossLimit) {
    return "blocked";
  }
  if (weight >= positionCap * 0.9 || position.pnl_pct <= -lossLimit * 0.8) {
    return "watch";
  }
  return "pass";
}

function strategyLabel(strategyId: string): string {
  if (strategyId === "intraday_macd") {
    return "策略一";
  }
  if (strategyId === "trend_portfolio") {
    return "策略二";
  }
  return "券商持仓";
}

function strategyDetail(strategyId: string): string {
  if (strategyId === "intraday_macd") {
    return "日内 MACD";
  }
  if (strategyId === "trend_portfolio") {
    return "中长线持仓";
  }
  return "实时同步";
}

function riskLabel(risk: PositionRisk): string {
  if (risk === "blocked") {
    return "需处理";
  }
  return risk === "watch" ? "关注" : "正常";
}

function money(value: number, digits = 0): string {
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(value);
}

function pct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function tone(value: number): "gain" | "loss" | "" {
  if (value > 0) {
    return "gain";
  }
  return value < 0 ? "loss" : "";
}
</script>

<template>
  <section class="position-management-view">
    <header class="position-page-head">
      <div>
        <p class="eyebrow">POSITION CONTROL</p>
        <h2>持仓管理</h2>
        <p>监控券商持仓、策略归属、资金占用与止损边界。</p>
      </div>
      <button class="text-button" type="button" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="16" />
        <span>刷新持仓</span>
      </button>
    </header>

    <section class="position-metrics">
      <article>
        <div class="position-metric-icon"><WalletCards :size="23" /></div>
        <div><span>持仓总市值</span><strong>{{ money(totalMarketValue) }}</strong><small>{{ account?.currency ?? "USD/HKD" }}</small></div>
      </article>
      <article>
        <div class="position-metric-icon"><Activity :size="23" /></div>
        <div><span>持仓浮盈亏</span><strong :class="tone(totalPnl)">{{ money(totalPnl) }}</strong><small :class="tone(totalPnlPct)">{{ pct(totalPnlPct) }}</small></div>
      </article>
      <article>
        <div class="position-metric-icon"><PieChart :size="23" /></div>
        <div><span>总仓位占比</span><strong>{{ utilizationPct.toFixed(1) }}%</strong><small>按账户总权益计算</small></div>
      </article>
      <article>
        <div class="position-metric-icon"><Layers3 :size="23" /></div>
        <div><span>持仓标的</span><strong>{{ positions.length }}</strong><small>多 {{ positions.filter((item) => item.side === "long").length }} / 空 {{ positions.filter((item) => item.side === "short").length }}</small></div>
      </article>
    </section>

    <div class="position-workspace">
      <article class="position-table-panel">
        <header class="position-panel-head">
          <div>
            <h3>当前持仓</h3>
            <p>数据来自当前运行模式对应的券商账户</p>
          </div>
          <span>{{ filteredRows.length }} 个标的</span>
        </header>

        <div class="position-filter-tabs">
          <button
            v-for="tab in filterTabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeFilter === tab.key }"
            @click="activeFilter = tab.key"
          >
            <span>{{ tab.label }}</span>
            <strong>{{ tab.count }}</strong>
          </button>
        </div>

        <div class="position-table-wrap">
          <table class="position-table">
            <thead>
              <tr>
                <th>标的</th>
                <th>策略</th>
                <th>方向</th>
                <th>数量</th>
                <th>成本 / 现价</th>
                <th>市值</th>
                <th>仓位</th>
                <th>浮动盈亏</th>
                <th>持仓</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="position in filteredRows" :key="position.symbol">
                <td>
                  <div class="position-symbol-cell">
                    <strong>{{ position.symbol }}</strong>
                    <span>{{ position.name }}</span>
                    <small>{{ position.market }}</small>
                  </div>
                </td>
                <td><strong>{{ position.strategyLabel }}</strong><small>{{ position.strategyDetail }}</small></td>
                <td>
                  <span class="position-side" :class="position.side">
                    <ArrowUpRight v-if="position.side === 'long'" :size="14" />
                    <ArrowDownRight v-else :size="14" />
                    {{ position.side === "long" ? "多头" : "空头" }}
                  </span>
                </td>
                <td>{{ money(position.quantity) }}</td>
                <td><strong>{{ money(position.avg_price, 2) }}</strong><small>{{ money(position.last_price, 2) }}</small></td>
                <td><strong>{{ money(position.market_value) }}</strong></td>
                <td>
                  <div class="position-weight-cell">
                    <strong>{{ position.weightPct.toFixed(1) }}%</strong>
                    <span><i :style="{ width: `${Math.min(position.weightPct * 5, 100)}%` }" /></span>
                  </div>
                </td>
                <td><strong :class="tone(position.pnl)">{{ money(position.pnl) }}</strong><small :class="tone(position.pnl_pct)">{{ pct(position.pnl_pct) }}</small></td>
                <td>{{ position.holding_days === 0 ? "当日" : `${position.holding_days} 天` }}</td>
                <td><span class="position-risk" :class="position.risk">{{ position.riskLabel }}</span></td>
              </tr>
              <tr v-if="filteredRows.length === 0">
                <td colspan="10" class="position-empty">
                  <BriefcaseBusiness :size="25" />
                  <strong>当前筛选下暂无持仓</strong>
                  <span>策略成交后，券商持仓会自动同步到这里。</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <aside class="position-rail">
        <section class="position-rail-card">
          <header><div><PieChart :size="18" /><h3>仓位分布</h3></div><span>总计 {{ utilizationPct.toFixed(1) }}%</span></header>
          <div class="allocation-list">
            <article v-for="position in allocationRows" :key="position.symbol">
              <div><strong>{{ position.symbol }}</strong><span>{{ position.strategyLabel }}</span></div>
              <div><strong>{{ position.weightPct.toFixed(1) }}%</strong><span>{{ money(position.market_value) }}</span></div>
              <span class="allocation-track"><i :style="{ width: `${Math.min(position.weightPct * 5, 100)}%` }" /></span>
            </article>
            <p v-if="allocationRows.length === 0" class="rail-empty">暂无仓位分布</p>
          </div>
        </section>

        <section class="position-rail-card">
          <header><div><ShieldCheck :size="18" /><h3>持仓风控</h3></div><span>实时校验</span></header>
          <div class="position-risk-summary">
            <article><span class="risk-dot pass"></span><div><strong>正常</strong><small>仓位与止损距离正常</small></div><b>{{ riskCounts.pass }}</b></article>
            <article><span class="risk-dot watch"></span><div><strong>关注</strong><small>接近仓位或止损阈值</small></div><b>{{ riskCounts.watch }}</b></article>
            <article><span class="risk-dot blocked"></span><div><strong>需处理</strong><small>达到强制风控条件</small></div><b>{{ riskCounts.blocked }}</b></article>
          </div>
          <p class="position-risk-note">日内仓位按策略一止损和仓位比例校验；中长线仓位按单标的上限和最大回撤校验。</p>
        </section>
      </aside>
    </div>
  </section>
</template>

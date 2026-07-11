<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  CircleAlert,
  Layers3,
  PieChart,
  RefreshCw,
  ShieldCheck,
  WalletCards,
  X
} from "lucide-vue-next";
import { closeUnassignedPositions, updatePositionRiskSetting } from "../api/client";
import type {
  AccountSummary,
  Order,
  Position,
  PositionRiskSetting,
  StrategyConfig
} from "../api/types";

type PositionFilter = "all" | "intraday" | "trend" | "maAtr" | "unassigned";
type PositionRisk = "pass" | "watch" | "triggered" | "closing" | "manual";

interface AttemptRecord {
  symbol: string;
  submitted: boolean;
  reasons: string[];
  at: number;
}

// 已尝试平仓的状态细分:
// - "submitted" : 后端确认下单成功
// - "pending"   : 后端返回失败,但失败原因包含"持仓不足"——通常意味着单子已经挂上、
//                 券商因可用持仓被冻结而拒,需要去券商客户端核对,而不是再发一次
// - "failed"    : 真正的提交失败(网络错误、订单被拒等)
type AttemptStatus = "submitted" | "pending" | "failed";

interface PositionRow extends Position {
  strategyLabel: string;
  strategyDetail: string;
  weightPct: number;
  risk: PositionRisk;
  riskLabel: string;
  riskDetail: string;
  attempt: AttemptRecord | null;
  attemptStatus: AttemptStatus | null;
}

const props = defineProps<{
  account: AccountSummary | null;
  orders: Order[];
  positions: Position[];
  strategies: StrategyConfig[];
  loading: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
}>();

const activeFilter = ref<PositionFilter>("all");
const closePending = ref(false);
const closeMessage = ref("");
const selectedPosition = ref<PositionRow | null>(null);
const stopLossPct = ref(2);
const takeProfitR = ref(2.5);
const immediateEffect = ref(true);
const riskSavePending = ref(false);
const riskSaveError = ref("");
const confirmRiskSave = ref(false);

// 记录已尝试过平仓的标的,避免用户反复点按钮导致后端反复向下单系统发"持仓不足"的废单。
// 用 sessionStorage 让页面刷新后仍记得"这一批已经试过了"。
const ATTEMPT_KEY = "unassigned-close-attempts";
const attemptedCloses = ref<Record<string, AttemptRecord>>({});

try {
  const stored = sessionStorage.getItem(ATTEMPT_KEY);
  if (stored) {
    attemptedCloses.value = JSON.parse(stored) as Record<string, AttemptRecord>;
  }
} catch {
  // sessionStorage 不可用或损坏,忽略即可
}

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
    const assessment = positionRisk(position);
    const attempt = attemptedCloses.value[position.symbol] ?? null;
    const attemptStatus = attempt ? attemptStatusOf(attempt) : null;
    // 有 attempt 时,优先用它的状态覆盖默认风控标签
    let risk: PositionRisk = assessment.risk;
    let riskLabelText: string = riskLabel(assessment.risk);
    let riskDetailText: string = assessment.detail;
    if (attemptStatus === "submitted") {
      risk = "closing";
      riskLabelText = "已提交";
      riskDetailText = attempt?.reasons.join(" / ") ?? "平仓委托已发送";
    } else if (attemptStatus === "pending") {
      risk = "closing";
      riskLabelText = "已挂单";
      riskDetailText = "请到券商客户端核对委托";
    } else if (attemptStatus === "failed") {
      risk = "manual";
      riskLabelText = "提交失败";
      riskDetailText = attempt?.reasons.join(" / ") ?? "平仓委托失败";
    }
    return {
      ...position,
      strategyLabel: strategyLabel(position.strategy_id),
      strategyDetail: strategyDetail(position.strategy_id),
      weightPct: positionWeight(position),
      risk,
      riskLabel: riskLabelText,
      riskDetail: riskDetailText,
      attempt,
      attemptStatus,
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
  if (activeFilter.value === "maAtr") {
    return positionRows.value.filter((position) => position.strategy_id === "ma_atr_intraday");
  }
  if (activeFilter.value === "unassigned") {
    return positionRows.value.filter((position) => !isKnownStrategy(position.strategy_id));
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
  },
  {
    key: "maAtr" as const,
    label: "策略三 · MA+MACD+ATR",
    count: props.positions.filter((position) => position.strategy_id === "ma_atr_intraday").length
  },
  {
    key: "unassigned" as const,
    label: "未归属",
    count: props.positions.filter((position) => !isKnownStrategy(position.strategy_id)).length
  }
]);

const allocationRows = computed(() =>
  [...positionRows.value].sort((left, right) => right.market_value - left.market_value)
);

const riskCounts = computed(() => ({
  pass: positionRows.value.filter((position) => position.risk === "pass").length,
  watch: positionRows.value.filter((position) => position.risk === "watch").length,
  triggered: positionRows.value.filter((position) => position.risk === "triggered").length,
  closing: positionRows.value.filter((position) => position.risk === "closing").length,
  manual: positionRows.value.filter((position) => position.risk === "manual").length
}));

const unassignedRows = computed(() =>
  positionRows.value.filter((position) => !isKnownStrategy(position.strategy_id))
);

// 还需要尝试平仓的未归属标的:从未提交过平仓请求的
const unassignedRemainingCount = computed(
  () =>
    unassignedRows.value.filter((position) => !attemptedCloses.value[position.symbol])
      .length
);

const stopPrice = computed(() =>
  selectedPosition.value
    ? riskPrice(selectedPosition.value, stopLossPct.value, false)
    : 0
);

const takeProfitPrice = computed(() =>
  selectedPosition.value
    ? riskPrice(selectedPosition.value, stopLossPct.value * takeProfitR.value, true)
    : 0
);

const riskDistance = computed(() =>
  selectedPosition.value ? selectedPosition.value.avg_price * (stopLossPct.value / 100) : 0
);

const targetDistance = computed(() => riskDistance.value * takeProfitR.value);

const newRiskAlreadyTriggered = computed(() => {
  const position = selectedPosition.value;
  if (!position || !immediateEffect.value) return false;
  return position.side === "long"
    ? position.last_price <= stopPrice.value || position.last_price >= takeProfitPrice.value
    : position.last_price >= stopPrice.value || position.last_price <= takeProfitPrice.value;
});

function strategyParam(strategyId: string, key: string, fallback: number): number {
  const strategy = props.strategies.find((item) => item.id === strategyId);
  const value = strategy?.params[key];
  return typeof value === "number" ? value : fallback;
}

function defaultRiskSetting(position: Position): { stopLossPct: number; takeProfitR: number } {
  if (position.strategy_id === "ma_atr_intraday") {
    const stop = strategyParam("ma_atr_intraday", "stop_loss_pct", 1.5);
    return {
      stopLossPct: stop,
      takeProfitR: strategyParam("ma_atr_intraday", "take_profit_pct", 3) / stop
    };
  }
  if (position.strategy_id === "trend_portfolio") {
    const stop = strategyParam("trend_portfolio", "max_symbol_drawdown_pct", 18);
    return {
      stopLossPct: stop,
      takeProfitR: strategyParam("trend_portfolio", "take_profit_pct", 20) / stop
    };
  }
  const stop = strategyParam("intraday_macd", "stop_loss_pct", 1.5);
  return {
    stopLossPct: stop,
    takeProfitR: strategyParam("intraday_macd", "take_profit_1_pct", 2) / stop
  };
}

function riskPrice(position: Position, distancePct: number, profit: boolean): number {
  const direction = position.side === "long" ? 1 : -1;
  const signedDirection = profit ? direction : -direction;
  return position.avg_price * (1 + signedDirection * distancePct / 100);
}

function settingPrice(position: Position, setting: PositionRiskSetting, profit: boolean): number {
  const distancePct = profit
    ? setting.stop_loss_pct * setting.take_profit_r
    : setting.stop_loss_pct;
  return riskPrice(position, distancePct, profit);
}

function openRiskSetting(position: PositionRow): void {
  if (position.risk === "closing") return;
  const defaults = defaultRiskSetting(position);
  selectedPosition.value = position;
  stopLossPct.value = position.risk_setting?.stop_loss_pct ?? defaults.stopLossPct;
  takeProfitR.value = position.risk_setting?.take_profit_r ?? defaults.takeProfitR;
  immediateEffect.value = position.risk_setting?.active ?? true;
  riskSaveError.value = "";
}

function closeRiskSetting(): void {
  if (riskSavePending.value) return;
  selectedPosition.value = null;
  confirmRiskSave.value = false;
  riskSaveError.value = "";
}

function requestRiskSave(): void {
  if (!selectedPosition.value || stopLossPct.value <= 0 || takeProfitR.value <= 0) return;
  confirmRiskSave.value = true;
}

async function saveRiskSetting(): Promise<void> {
  const position = selectedPosition.value;
  if (!position || riskSavePending.value) return;
  riskSavePending.value = true;
  riskSaveError.value = "";
  try {
    await updatePositionRiskSetting(position.market, position.symbol, {
      stop_loss_pct: Number(stopLossPct.value),
      take_profit_r: Number(takeProfitR.value),
      active: immediateEffect.value
    });
    confirmRiskSave.value = false;
    selectedPosition.value = null;
    emit("refresh");
  } catch (err) {
    confirmRiskSave.value = false;
    riskSaveError.value = err instanceof Error ? err.message : "持仓风控保存失败";
  } finally {
    riskSavePending.value = false;
  }
}

function positionWeight(position: Position): number {
  const equity = props.account?.total_equity ?? 0;
  return equity > 0 ? (position.market_value / equity) * 100 : 0;
}

function isKnownStrategy(strategyId: string): boolean {
  return ["intraday_macd", "trend_portfolio", "ma_atr_intraday"].includes(strategyId);
}

function attemptStatusOf(attempt: AttemptRecord): AttemptStatus {
  if (attempt.submitted) {
    return "submitted";
  }
  const reasons = attempt.reasons.join(" / ");
  // 后端实际返回的是"下单失败：券商未返回订单号"或富途抛出的异常文本,
  // 日志里出现了"持仓不足"——但到前端时异常文本并不包含"持仓不足"这几个字。
  // 改为:只要 submitted=false 都归为"已挂单",因为富途模拟盘环境通常已在
  // 客户端挂上了订单,只是调用方拿不到 order_id 而已。用户去券商确认即可。
  return "pending";
}

function positionRisk(position: Position): { risk: PositionRisk; detail: string } {
  const weight = positionWeight(position);
  const intraday = position.strategy_id === "intraday_macd";
  const positionCap = intraday
    ? strategyParam("intraday_macd", "position_fraction_pct", 10)
    : strategyParam("trend_portfolio", "single_position_cap_pct", 15);
  const strategyLossLimit = intraday
    ? strategyParam("intraday_macd", "stop_loss_pct", 1.5)
    : position.strategy_id === "ma_atr_intraday"
      ? strategyParam("ma_atr_intraday", "stop_loss_pct", 1.5)
      : strategyParam("trend_portfolio", "max_symbol_drawdown_pct", 18);
  const lossLimit = position.risk_setting?.active
    ? position.risk_setting.stop_loss_pct
    : strategyLossLimit;

  const triggers = riskTriggers(position, weight, positionCap, lossLimit, intraday);
  if (triggers.length > 0) {
    const closeOrder = latestCloseOrder(position);
    if (closeOrder?.status === "submitted") {
      return { risk: "closing", detail: `已提交自动平仓单：${triggers.join(" / ")}` };
    }
    if (closeOrder?.status === "rejected" || closeOrder?.status === "cancelled") {
      return { risk: "manual", detail: `自动平仓未完成：${orderStatusText(closeOrder.status)}` };
    }
    return { risk: "triggered", detail: triggers.join(" / ") };
  }
  if (weight >= positionCap * 0.9 || position.pnl_pct <= -lossLimit * 0.8) {
    return { risk: "watch", detail: "接近仓位上限或止损线" };
  }
  return { risk: "pass", detail: "仓位与止损距离正常" };
}

function riskTriggers(
  position: Position,
  weight: number,
  positionCap: number,
  lossLimit: number,
  intraday: boolean
): string[] {
  const triggers: string[] = [];
  if (intraday && position.holding_days > 0) {
    triggers.push("日内仓隔夜");
  }
  if (weight > positionCap) {
    triggers.push(`仓位超限 ${weight.toFixed(1)}%/${positionCap.toFixed(1)}%`);
  }
  if (position.pnl_pct <= -lossLimit) {
    triggers.push(`触发止损 ${pct(position.pnl_pct)}/${pct(-lossLimit)}`);
  }
  return triggers;
}

function latestCloseOrder(position: Position): Order | null {
  const closeSides = position.side === "long" ? ["sell"] : ["cover"];
  return (
    [...props.orders]
      .filter(
        (order) =>
          order.symbol === position.symbol &&
          order.strategy_id === position.strategy_id &&
          closeSides.includes(order.side)
      )
      .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0] ?? null
  );
}

function strategyLabel(strategyId: string): string {
  if (strategyId === "intraday_macd") {
    return "策略一";
  }
  if (strategyId === "trend_portfolio") {
    return "策略二";
  }
  if (strategyId === "ma_atr_intraday") {
    return "策略三";
  }
  return "未归属";
}

function strategyDetail(strategyId: string): string {
  if (strategyId === "intraday_macd") {
    return "日内 MACD";
  }
  if (strategyId === "trend_portfolio") {
    return "中长线持仓";
  }
  if (strategyId === "ma_atr_intraday") {
    return "多周期 MA + MACD + ATR";
  }
  return "券商同步 · 未恢复策略来源";
}

function riskLabel(risk: PositionRisk): string {
  if (risk === "triggered") {
    return "已触发风控";
  }
  if (risk === "closing") {
    return "平仓中";
  }
  if (risk === "manual") {
    return "需人工介入";
  }
  return risk === "watch" ? "关注" : "正常";
}

function orderStatusText(status: Order["status"]): string {
  if (status === "rejected") {
    return "订单被拒";
  }
  if (status === "cancelled") {
    return "订单已撤";
  }
  return status;
}

async function closeUnassigned(): Promise<void> {
  if (unassignedRows.value.length === 0 || closePending.value) {
    return;
  }
  const symbols = unassignedRows.value.map((position) => position.symbol).join("、");
  const confirmed = window.confirm(`确认提交平仓单？\n\n未归属持仓：${symbols}\n\n此操作会按当前券商持仓方向平仓。`);
  if (!confirmed) {
    return;
  }
  closePending.value = true;
  closeMessage.value = "";
  try {
    const result = await closeUnassignedPositions();
    closeMessage.value = `已提交 ${result.submitted}/${result.results.length} 笔未归属平仓单`;
    // 记录每只标的的尝试结果，标记 submission 状态阻止重复提交
    for (const item of result.results) {
      attemptedCloses.value[item.symbol] = {
        symbol: item.symbol,
        submitted: item.submitted,
        reasons: item.reasons,
        at: Date.now(),
      };
    }
    // 持久化到 sessionStorage,防止刷新后重复提交
    try {
      sessionStorage.setItem(ATTEMPT_KEY, JSON.stringify(attemptedCloses.value));
    } catch {
      // 不可写时忽略
    }
    emit("refresh");
  } catch (err) {
    closeMessage.value = err instanceof Error ? err.message : "未归属平仓提交失败";
  } finally {
    closePending.value = false;
  }
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

function oneDecimal(value: number): string {
  return Number(value || 0).toFixed(1);
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
        <h2>持仓风控</h2>
        <p>监控券商持仓、自动平仓状态、资金占用与止损边界。</p>
      </div>
      <button class="text-button" type="button" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="16" />
        <span>刷新持仓</span>
      </button>
    </header>

    <section v-if="unassignedRows.length > 0 || closeMessage" class="unassigned-action-bar">
      <div>
        <CircleAlert :size="18" />
        <span>{{ unassignedRows.length }} 个未归属持仓</span>
        <small>{{ closeMessage || "无法恢复策略来源，建议先平仓或手动核对券商账户。" }}</small>
      </div>
      <button
        class="text-button danger"
        type="button"
        :disabled="closePending || loading || unassignedRemainingCount === 0"
        @click="closeUnassigned"
      >
        <span v-if="closePending">提交中</span>
        <span v-else-if="unassignedRemainingCount === 0">已全部提交</span>
        <span v-else>平掉未归属 ({{ unassignedRemainingCount }})</span>
      </button>
    </section>

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
                <th>风控设置</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="position in filteredRows"
                :key="position.symbol"
                :class="{ selected: selectedPosition?.symbol === position.symbol }"
              >
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
                <td>
                  <span class="position-risk" :class="position.risk" :title="position.riskDetail">
                    {{ position.riskLabel }}
                  </span>
                </td>
                <td>
                  <div class="position-risk-setting-cell">
                    <button
                      class="position-risk-setting-button"
                      type="button"
                      :disabled="position.risk === 'closing'"
                      :title="position.risk === 'closing' ? '已有平仓委托，不能重复设置风控' : ''"
                      @click="openRiskSetting(position)"
                    >
                      {{ position.risk === "closing" ? "平仓处理中" : position.risk_setting ? "修改风控" : "止盈止损设置" }}
                    </button>
                    <template v-if="position.risk_setting">
                      <small>
                        止损 {{ position.risk_setting.stop_loss_pct.toFixed(1) }}% ·
                        {{ money(settingPrice(position, position.risk_setting, false), 2) }}
                      </small>
                      <small>
                        止盈 {{ position.risk_setting.take_profit_r.toFixed(1) }}R ·
                        {{ money(settingPrice(position, position.risk_setting, true), 2) }}
                      </small>
                    </template>
                    <small v-else>使用策略默认</small>
                  </div>
                </td>
              </tr>
              <tr v-if="filteredRows.length === 0">
                <td colspan="11" class="position-empty">
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
          <header><div><ShieldCheck :size="18" /><h3>自动风控</h3></div><span>实时校验</span></header>
          <div class="position-risk-summary">
            <article><span class="risk-dot pass"></span><div><strong>正常</strong><small>仓位与止损距离正常</small></div><b>{{ riskCounts.pass }}</b></article>
            <article><span class="risk-dot watch"></span><div><strong>关注</strong><small>接近仓位或止损阈值</small></div><b>{{ riskCounts.watch }}</b></article>
            <article><span class="risk-dot triggered"></span><div><strong>已触发风控</strong><small>达到自动平仓条件</small></div><b>{{ riskCounts.triggered }}</b></article>
            <article><span class="risk-dot closing"></span><div><strong>平仓中</strong><small>已有自动平仓委托</small></div><b>{{ riskCounts.closing }}</b></article>
            <article><span class="risk-dot manual"></span><div><strong>需人工介入</strong><small>自动委托失败或撤销</small></div><b>{{ riskCounts.manual }}</b></article>
          </div>
          <p class="position-risk-note">风控触发后应由后端自动平仓；只有订单失败、撤销或网关异常时才需要人工介入。</p>
        </section>
      </aside>
    </div>

    <Teleport to="body">
      <Transition name="position-drawer">
        <div v-if="selectedPosition" class="position-risk-drawer-mask" @click.self="closeRiskSetting">
          <aside class="position-risk-drawer" aria-label="止盈止损设置">
            <header class="position-risk-drawer-head">
              <h2>止盈止损设置</h2>
              <button type="button" aria-label="关闭" @click="closeRiskSetting"><X :size="20" /></button>
            </header>

            <div class="position-risk-drawer-body">
              <section class="risk-position-identity">
                <div>
                  <strong>{{ selectedPosition.symbol }}</strong>
                  <span :class="selectedPosition.side">
                    {{ selectedPosition.side === "long" ? "多头" : "空头" }}
                  </span>
                </div>
                <p><span>当前持仓平均成本</span><strong>{{ money(selectedPosition.avg_price, 2) }}</strong></p>
              </section>

              <label class="risk-setting-field">
                <span>止损比例（%）</span>
                <input v-model.number="stopLossPct" type="number" min="0.1" max="100" step="0.1" />
              </label>

              <label class="risk-setting-field">
                <span>止盈倍数（R）</span>
                <input v-model.number="takeProfitR" type="number" min="0.1" max="20" step="0.1" />
              </label>

              <div class="risk-setting-toggle-row">
                <div><strong>立即生效</strong><small>关闭后保存为暂不执行的持仓设置</small></div>
                <button
                  class="risk-setting-toggle"
                  :class="{ active: immediateEffect }"
                  type="button"
                  role="switch"
                  :aria-checked="immediateEffect"
                  @click="immediateEffect = !immediateEffect"
                ><i /></button>
              </div>

              <section class="risk-price-preview">
                <header><strong>计算预览</strong><span>基于平均成本计算</span></header>
                <div>
                  <p><span>止损价</span><strong class="loss">{{ money(stopPrice, 2) }}</strong></p>
                  <p><span>止盈价</span><strong class="gain">{{ money(takeProfitPrice, 2) }}</strong></p>
                  <p><span>风险距离</span><strong>{{ money(riskDistance, 2) }}</strong></p>
                  <p><span>目标收益</span><strong>{{ money(targetDistance, 2) }}</strong></p>
                  <p><span>盈亏比</span><strong>1 : {{ oneDecimal(takeProfitR) }}</strong></p>
                </div>
                <small>价格基于当前持仓平均成本计算；加仓后将自动重新计算。</small>
              </section>

              <div class="risk-setting-warning" :class="{ urgent: newRiskAlreadyTriggered }">
                <CircleAlert :size="17" />
                <span>当前价格若已触及新止损或止盈条件，保存后可能立即触发平仓。</span>
              </div>
              <p v-if="riskSaveError" class="risk-setting-error">{{ riskSaveError }}</p>
            </div>

            <footer class="position-risk-drawer-actions">
              <button type="button" @click="closeRiskSetting">取消</button>
              <button
                class="primary"
                type="button"
                :disabled="stopLossPct <= 0 || takeProfitR <= 0"
                @click="requestRiskSave"
              >确认并应用</button>
            </footer>
          </aside>
        </div>
      </Transition>

      <Transition name="fade">
        <div v-if="confirmRiskSave && selectedPosition" class="risk-confirm-mask">
          <section class="risk-confirm-dialog">
            <div class="risk-confirm-icon"><ShieldCheck :size="23" /></div>
            <h3>确认应用新的止盈止损？</h3>
            <p>
              {{ selectedPosition.symbol }} 将使用止损 {{ oneDecimal(stopLossPct) }}%、
              止盈 {{ oneDecimal(takeProfitR) }}R。
              <template v-if="immediateEffect">保存后立即进入自动风控检查。</template>
              <template v-else>该设置将保存但暂不执行。</template>
            </p>
            <div class="risk-confirm-levels">
              <span>止损价 <strong class="loss">{{ money(stopPrice, 2) }}</strong></span>
              <span>止盈价 <strong class="gain">{{ money(takeProfitPrice, 2) }}</strong></span>
            </div>
            <div class="risk-confirm-actions">
              <button type="button" :disabled="riskSavePending" @click="confirmRiskSave = false">返回修改</button>
              <button class="primary" type="button" :disabled="riskSavePending" @click="saveRiskSetting">
                {{ riskSavePending ? "保存中…" : "确认应用" }}
              </button>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch, type Component } from "vue";
import {
  Activity,
  BarChart3,
  Clock3,
  LockKeyhole,
  PlayCircle,
  Power,
  ShieldCheck,
  Target,
  WalletCards
} from "lucide-vue-next";
import type { BacktestResult, Market, ParamValue, StrategyConfig } from "../api/types";
import { backtestTradesCsvUrl } from "../api/client";

interface ParamDefinition {
  key: string;
  label: string;
  hint: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  displayScale?: number;
}

interface ParamGroup {
  title: string;
  icon: Component;
  params: ParamDefinition[];
}

interface RuleGroup {
  title: string;
  icon: Component;
  items: string[];
}

const props = defineProps<{
  strategy: StrategyConfig;
  backtest: BacktestResult | null;
  backtestRunning: boolean;
  backtestProgress: number;
  backtestProgressLabel: string;
  backtestError: string | null;
}>();

const emit = defineEmits<{
  toggle: [StrategyConfig];
  updateParam: [StrategyConfig, string, ParamValue];
  backtest: [strategyId: string, market: Market];
}>();

const paramDraft = reactive<Record<string, ParamValue>>({});
const activeParamKey = ref<string | null>(null);
const selectedBacktestMarket = ref<Market>(props.strategy.markets[0] ?? "HK");
const visibleTradeCount = ref(10);
const pendingParams = reactive<Record<string, ParamValue>>({});
const pendingTimers = new Map<string, number>();

const INTRADAY_PARAM_GROUPS: ParamGroup[] = [
  {
    title: "MACD 信号",
    icon: BarChart3,
    params: [
      { key: "fast_ema", label: "快线周期", hint: "三周期信号共同使用的 MACD 快线", unit: "根", min: 2, max: 60, step: 1 },
      { key: "slow_ema", label: "慢线周期", hint: "必须大于快线周期", unit: "根", min: 3, max: 120, step: 1 },
      { key: "signal_ema", label: "信号线周期", hint: "MACD DEA 平滑周期", unit: "根", min: 2, max: 60, step: 1 }
    ]
  },
  {
    title: "K线周期",
    icon: BarChart3,
    params: [
      { key: "slow_k_minutes", label: "大周期", hint: "三周期中最慢的K线(分钟)", unit: "分钟", min: 3, max: 120, step: 1 },
      { key: "mid_k_minutes", label: "中周期", hint: "中间周期的K线(分钟)", unit: "分钟", min: 1, max: 60, step: 1 },
      { key: "fast_k_minutes", label: "小周期", hint: "最小周期的K线(同时也是触发评估周期)", unit: "分钟", min: 1, max: 30, step: 1 }
    ]
  },
  {
    title: "交易时段",
    icon: Clock3,
    params: [
      { key: "open_after_minutes", label: "开盘等待", hint: "开盘后等待多少分钟再允许开仓", unit: "分钟", min: 0, max: 240, step: 5 },
      { key: "close_before_minutes", label: "尾盘停开", hint: "收盘前多少分钟停止新开仓", unit: "分钟", min: 0, max: 240, step: 5 }
    ]
  },
  {
    title: "盘前筛选",
    icon: Activity,
    params: [
      { key: "min_turnover", label: "最低日均成交额", hint: "过滤流动性不足的标的", unit: "万元", min: 0, max: 10000000000, step: 100000, displayScale: 10000 },
      { key: "min_amplitude_pct", label: "前日振幅下限", hint: "前一交易日振幅最小值", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "max_amplitude_pct", label: "前日振幅上限", hint: "必须不小于振幅下限", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "min_price", label: "最低股价", hint: "过滤价格过低的标的", unit: "元", min: 0, max: 100000, step: 0.5 },
      { key: "min_turnover_rate", label: "最低换手率", hint: "按成交额与总市值计算", unit: "%", min: 0, max: 100, step: 0.1 },
      { key: "auto_min_score", label: "自动选股评分门槛", hint: "自动筛选标的的最低评分，低于此分不进入候选池", unit: "", min: 0, max: 1, step: 0.05 }
    ]
  },
  {
    title: "仓位与风控",
    icon: WalletCards,
    params: [
      { key: "position_fraction_pct", label: "单次开仓仓位", hint: "按账户总权益计算目标市值", unit: "%", min: 1, max: 30, step: 1 },
      { key: "max_positions", label: "最大同时持仓", hint: "日内策略允许持有的标的上限", unit: "只", min: 1, max: 10, step: 1 },
      { key: "max_daily_loss_pct", label: "单日最大亏损", hint: "触发后当日停止所有新交易", unit: "%", min: 0.5, max: 10, step: 0.1 }
    ]
  }
];

const TREND_PARAM_GROUPS: ParamGroup[] = [
  {
    title: "组合与建仓",
    icon: WalletCards,
    params: [
      { key: "single_position_cap_pct", label: "单只最大仓位", hint: "单一标的占账户总权益上限", unit: "%", min: 1, max: 50, step: 1 },
      { key: "target_positions_min", label: "目标持仓下限", hint: "组合分散持仓的最少标的数", unit: "只", min: 1, max: 20, step: 1 },
      { key: "target_positions_max", label: "目标持仓上限", hint: "组合分散持仓的最多标的数", unit: "只", min: 1, max: 30, step: 1 },
      { key: "first_entry_fraction_pct", label: "首次建仓比例", hint: "第一批建仓占目标仓位的比例", unit: "%", min: 10, max: 100, step: 5 }
    ]
  },
  {
    title: "退出与调仓",
    icon: Target,
    params: [
      { key: "max_symbol_drawdown_pct", label: "单标的最大回撤", hint: "触发后无条件止损", unit: "%", min: 1, max: 50, step: 1 },
      { key: "rebalance_months", label: "最长持仓周期", hint: "到期后强制复核并调仓", unit: "个月", min: 1, max: 24, step: 1 },
      { key: "hot_gain_block_pct", label: "短期涨幅禁买线", hint: "超过阈值时禁止追高建仓", unit: "%", min: 10, max: 100, step: 5 }
    ]
  }
];

const MA_ATR_PARAM_GROUPS: ParamGroup[] = [
  {
    title: "K线周期",
    icon: BarChart3,
    params: [
      { key: "slow_k_minutes", label: "大周期", hint: "大级别趋势方向周期(分钟)", unit: "分钟", min: 5, max: 120, step: 5 },
      { key: "mid_k_minutes", label: "中周期", hint: "中短期趋势确认周期(分钟)", unit: "分钟", min: 3, max: 60, step: 1 },
      { key: "fast_k_minutes", label: "小周期", hint: "入场触发周期(分钟)", unit: "分钟", min: 1, max: 30, step: 1 }
    ]
  },
  {
    title: "均线参数",
    icon: Activity,
    params: [
      { key: "slow_fast_ema", label: "大周期快线", hint: "1h EMA3", unit: "根", min: 1, max: 200, step: 1 },
      { key: "slow_slow_ema", label: "大周期慢线", hint: "1h EMA8", unit: "根", min: 1, max: 400, step: 1 },
      { key: "mid_fast_ema", label: "中周期快线", hint: "10m EMA11", unit: "根", min: 1, max: 200, step: 1 },
      { key: "mid_slow_ema", label: "中周期慢线", hint: "10m EMA30", unit: "根", min: 1, max: 400, step: 1 },
      { key: "fast_fast_ema", label: "小周期快线", hint: "5m EMA3", unit: "根", min: 1, max: 200, step: 1 },
      { key: "fast_slow_ema", label: "小周期慢线", hint: "5m EMA8", unit: "根", min: 1, max: 400, step: 1 }
    ]
  },
  {
    title: "MACD + ATR",
    icon: BarChart3,
    params: [
      { key: "macd_fast", label: "MACD 快线", hint: "MACD 快线周期", unit: "根", min: 2, max: 60, step: 1 },
      { key: "macd_slow", label: "MACD 慢线", hint: "MACD 慢线周期", unit: "根", min: 3, max: 120, step: 1 },
      { key: "macd_signal", label: "MACD 信号线", hint: "MACD DEA 平滑", unit: "根", min: 2, max: 60, step: 1 },
      { key: "atr_period", label: "ATR 周期", hint: "真实波幅计算周期", unit: "根", min: 1, max: 60, step: 1 },
      { key: "atr_multiplier", label: "ATR 止损倍数", hint: "ATR × 倍数 = 止损距离", unit: "倍", min: 0.5, max: 5, step: 0.1 }
    ]
  },
  {
    title: "止盈止损",
    icon: Target,
    params: [
      { key: "stop_loss_pct", label: "固定止损", hint: "价格相对开仓价反向多少百分比", unit: "%", min: 0.5, max: 20, step: 0.1 },
      { key: "take_profit_pct", label: "固定止盈", hint: "达到目标浮盈即平仓", unit: "%", min: 0.5, max: 30, step: 0.1 },
      { key: "trailing_start_pct", label: "移动止盈启动", hint: "浮盈达到N%后开启跟踪", unit: "%", min: 0.5, max: 20, step: 0.1 },
      { key: "trailing_stop_pct", label: "移动止盈回撤", hint: "从最高点回撤N%即平仓", unit: "%", min: 0.5, max: 10, step: 0.1 }
    ]
  },
  {
    title: "交易时段 + 盘前筛选",
    icon: Clock3,
    params: [
      { key: "open_after_minutes", label: "开盘等待", hint: "开盘后N分钟才允许开仓", unit: "分钟", min: 0, max: 240, step: 5 },
      { key: "close_before_minutes", label: "尾盘停开", hint: "收盘前N分钟停止新开仓", unit: "分钟", min: 0, max: 240, step: 5 },
      { key: "min_turnover", label: "最低成交额", hint: "自动选股成交额门槛", unit: "万元", min: 0, max: 10000000000, step: 100000, displayScale: 10000 },
      { key: "min_amplitude_pct", label: "最低振幅", hint: "前日振幅最小值", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "max_amplitude_pct", label: "最高振幅", hint: "前日振幅最大值", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "min_price", label: "最低股价", hint: "过滤价格过低的标的", unit: "元", min: 0, max: 100000, step: 0.5 },
      { key: "auto_min_score", label: "评分门槛", hint: "自动选股最低评分(0~1)", unit: "", min: 0, max: 1, step: 0.05 }
    ]
  },
  {
    title: "仓位与风控",
    icon: WalletCards,
    params: [
      { key: "position_fraction_pct", label: "单次开仓仓位", hint: "按账户总权益计算", unit: "%", min: 1, max: 30, step: 1 },
      { key: "max_positions", label: "最大持仓数", hint: "日内策略同时持仓标的上限", unit: "只", min: 1, max: 10, step: 1 },
      { key: "max_daily_loss_pct", label: "单日最大亏损", hint: "触发后当日停止新交易", unit: "%", min: 0.5, max: 10, step: 0.1 }
    ]
  }
];

const INTRADAY_RULES: RuleGroup[] = [
  {
    title: "信号引擎",
    icon: BarChart3,
    items: ["大/中/小三周期共振(可在 K线周期 中配置)", "三周期柱同向抬高开多、走低开空", "持仓柱体反向同步即全平", "进出场按最小周期收线评估"]
  },
  {
    title: "执行约束",
    icon: ShieldCheck,
    items: ["同一标的不重复加仓", "做空前校验可借券状态", "美股账户执行 PDT 检查", "港股午休时段不执行信号"]
  }
];

const TREND_RULES: RuleGroup[] = [
  {
    title: "趋势框架",
    icon: BarChart3,
    items: ["月线确定长期方向", "周线确认中期趋势", "日线回踩择机入场", "每月最后交易日重新筛选"]
  },
  {
    title: "硬性约束",
    icon: ShieldCheck,
    items: props.strategy.risk_controls
  }
];

watch(
  () => props.strategy.params,
  (params) => {
    for (const key of Object.keys(paramDraft)) {
      if (!(key in params) && activeParamKey.value !== key && !(key in pendingParams)) {
        delete paramDraft[key];
      }
    }
    for (const [key, value] of Object.entries(params)) {
      if (activeParamKey.value === key) {
        continue;
      }
      if (key in pendingParams) {
        if (Object.is(pendingParams[key], value)) {
          clearPendingParam(key);
        } else {
          continue;
        }
      }
      paramDraft[key] = value;
    }
  },
  { immediate: true, deep: true }
);

const stateLabel = computed(() => {
  if (!props.strategy.enabled) {
    return "已暂停";
  }
  return props.strategy.state === "running" ? "运行中" : props.strategy.state;
});

function strategyNumberParam(key: string, fallback: number): number {
  const value = props.strategy.params[key];
  return typeof value === "number" ? value : fallback;
}

const maAtrParamGroups = computed<ParamGroup[]>(() => {
  const hintByKey: Record<string, string> = {
    slow_fast_ema: `${strategyNumberParam("slow_k_minutes", 60)}分钟 EMA 快线`,
    slow_slow_ema: `${strategyNumberParam("slow_k_minutes", 60)}分钟 EMA 慢线`,
    mid_fast_ema: `${strategyNumberParam("mid_k_minutes", 10)}分钟 EMA 快线`,
    mid_slow_ema: `${strategyNumberParam("mid_k_minutes", 10)}分钟 EMA 慢线`,
    fast_fast_ema: `${strategyNumberParam("fast_k_minutes", 5)}分钟 EMA 快线`,
    fast_slow_ema: `${strategyNumberParam("fast_k_minutes", 5)}分钟 EMA 慢线`
  };

  return MA_ATR_PARAM_GROUPS.map((group) => ({
    ...group,
    params: group.params.map((param) => ({
      ...param,
      hint: hintByKey[param.key] ?? param.hint
    }))
  }));
});

const paramGroups = computed(() => {
  if (props.strategy.id === "intraday_macd") return INTRADAY_PARAM_GROUPS;
  if (props.strategy.id === "ma_atr_intraday") return maAtrParamGroups.value;
  return TREND_PARAM_GROUPS;
});

const maAtrRules = computed<RuleGroup[]>(() => {
  const slowMinutes = strategyNumberParam("slow_k_minutes", 60);
  const midMinutes = strategyNumberParam("mid_k_minutes", 10);
  const fastMinutes = strategyNumberParam("fast_k_minutes", 5);
  const slowFastEma = strategyNumberParam("slow_fast_ema", 3);
  const slowSlowEma = strategyNumberParam("slow_slow_ema", 8);
  const midFastEma = strategyNumberParam("mid_fast_ema", 11);
  const midSlowEma = strategyNumberParam("mid_slow_ema", 30);
  const fastFastEma = strategyNumberParam("fast_fast_ema", 3);
  const fastSlowEma = strategyNumberParam("fast_slow_ema", 8);
  const macdFast = strategyNumberParam("macd_fast", 12);
  const macdSlow = strategyNumberParam("macd_slow", 26);
  const macdSignal = strategyNumberParam("macd_signal", 9);
  const atrPeriod = strategyNumberParam("atr_period", 5);
  const atrMultiplier = strategyNumberParam("atr_multiplier", 1.2);
  const stopLoss = strategyNumberParam("stop_loss_pct", 1.5);
  const takeProfit = strategyNumberParam("take_profit_pct", 3);
  const trailingStart = strategyNumberParam("trailing_start_pct", 2);
  const trailingStop = strategyNumberParam("trailing_stop_pct", 1);
  const positionFraction = strategyNumberParam("position_fraction_pct", 10);
  const maxPositions = strategyNumberParam("max_positions", 3);
  const dailyLoss = strategyNumberParam("max_daily_loss_pct", 3);
  const trailingEnabled = props.strategy.params.trailing_enabled !== false;

  return [
    {
      title: "信号引擎",
      icon: BarChart3,
      items: [
        `${slowMinutes}分钟 EMA${slowFastEma}/${slowSlowEma} 定多空方向`,
        `${midMinutes}分钟 EMA${midFastEma}/${midSlowEma} 趋势确认`,
        `${fastMinutes}分钟 EMA${fastFastEma}/${fastSlowEma} 金叉死叉触发入场`,
        `MACD(${macdFast}, ${macdSlow}, ${macdSignal}) 金叉确认动能`,
        `ATR(${atrPeriod}) × ${atrMultiplier} 动态止损保护`
      ]
    },
    {
      title: "平仓规则",
      icon: Target,
      items: [
        `${fastMinutes}分钟 EMA${fastFastEma}/${fastSlowEma} 下穿(多) / 上穿(空)`,
        `MACD(${macdFast}, ${macdSlow}, ${macdSignal}) 死叉(多) / 金叉(空)`,
        `${midMinutes}分钟 EMA${midFastEma}/${midSlowEma} 反转`,
        `ATR(${atrPeriod}) × ${atrMultiplier} 动态止损 / 固定止损 ${stopLoss}%`,
        trailingEnabled
          ? `固定止盈 ${takeProfit}% / 移动止盈 ${trailingStart}% 启动，回撤 ${trailingStop}%`
          : `固定止盈 ${takeProfit}% / 移动止盈未启用`
      ]
    },
    {
      title: "执行约束",
      icon: ShieldCheck,
      items: [
        `单次开仓仓位 ${positionFraction}% / 最大同时持仓 ${maxPositions} 只`,
        `单日最大亏损 ${dailyLoss}%`,
        "同一标的跨策略排他，已有仓位优先"
      ]
    }
  ];
});

const ruleGroups = computed(() => {
  if (props.strategy.id === "intraday_macd") return INTRADAY_RULES;
  if (props.strategy.id === "ma_atr_intraday") return maAtrRules.value;
  return TREND_RULES;
});

const backtestMarkets = computed<Market[]>(() =>
  props.strategy.markets.length ? props.strategy.markets : ["HK", "US"]
);

watch(
  () => props.strategy.id,
  () => {
    selectedBacktestMarket.value = backtestMarkets.value[0] ?? "HK";
  }
);

watch(
  () => props.strategy.markets,
  (markets) => {
    if (!markets.includes(selectedBacktestMarket.value)) {
      selectedBacktestMarket.value = markets[0] ?? "HK";
    }
  },
  { deep: true }
);

const currentBacktest = computed(() =>
  props.backtest?.strategy_id === props.strategy.id && props.backtest.market === selectedBacktestMarket.value ? props.backtest : null
);

const backtestDownloadUrl = computed(() =>
  currentBacktest.value ? backtestTradesCsvUrl(currentBacktest.value.id) : ""
);

const visibleBacktestTrades = computed(() =>
  currentBacktest.value?.trade_rows.slice(0, visibleTradeCount.value) ?? []
);

const remainingTradeCount = computed(() =>
  Math.max(0, (currentBacktest.value?.trade_rows.length ?? 0) - visibleTradeCount.value)
);

watch(
  () => currentBacktest.value?.id,
  () => {
    visibleTradeCount.value = 10;
  }
);

function signedPercent(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function money(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2
  }).format(value);
}

function tradeSideLabel(side: string): string {
  return side === "short" ? "空头" : "多头";
}

function beginParamEdit(definition: ParamDefinition): void {
  activeParamKey.value = definition.key;
}

function displayParamValue(definition: ParamDefinition): ParamValue {
  const value = paramDraft[definition.key];
  if (value === "" || typeof value !== "number") return value;
  return value / (definition.displayScale ?? 1);
}

function displayParamStep(value: number, definition: ParamDefinition): number {
  return value / (definition.displayScale ?? 1);
}

function updateParamDraft(definition: ParamDefinition, event: Event): void {
  const target = event.target as HTMLInputElement;
  const scale = definition.displayScale ?? 1;
  paramDraft[definition.key] = target.value === "" ? "" : Number(target.value) * scale;
}

function commitParam(definition: ParamDefinition, event: Event): void {
  const target = event.target as HTMLInputElement;
  activeParamKey.value = null;
  const current = props.strategy.params[definition.key];
  const inputValue = target.value.trim();
  const value = typeof current === "number"
    ? Number(inputValue) * (definition.displayScale ?? 1)
    : inputValue;
  if (
    inputValue === "" ||
    (typeof value === "number" && !Number.isFinite(value))
  ) {
    paramDraft[definition.key] = current;
    return;
  }
  paramDraft[definition.key] = value;
  if (Object.is(value, current)) {
    return;
  }
  pendingParams[definition.key] = value;
  emit("updateParam", props.strategy, definition.key, value);
  const previousTimer = pendingTimers.get(definition.key);
  if (previousTimer !== undefined) {
    window.clearTimeout(previousTimer);
  }
  pendingTimers.set(
    definition.key,
    window.setTimeout(() => {
      clearPendingParam(definition.key);
      paramDraft[definition.key] = props.strategy.params[definition.key];
    }, 5000)
  );
}

function commitOnEnter(event: KeyboardEvent): void {
  (event.target as HTMLInputElement).blur();
}

function clearPendingParam(key: string): void {
  delete pendingParams[key];
  const timer = pendingTimers.get(key);
  if (timer !== undefined) {
    window.clearTimeout(timer);
    pendingTimers.delete(key);
  }
}

onBeforeUnmount(() => pendingTimers.forEach((timer) => window.clearTimeout(timer)));
</script>

<template>
  <article class="strategy-detail-shell" :class="{ muted: !strategy.enabled }">
    <header class="strategy-detail-head">
      <div>
        <p class="eyebrow">正在查看的策略配置</p>
        <h2>{{ strategy.name }}</h2>
        <p>参数修改后立即生效，安全约束由运行时代码强制执行。</p>
      </div>
      <div class="strategy-head-actions">
        <span class="strategy-state" :class="{ running: strategy.enabled }">{{ stateLabel }}</span>
        <button
          class="strategy-power"
          :class="{ active: strategy.enabled }"
          type="button"
          :title="strategy.enabled ? '暂停策略' : '开启策略'"
          @click="emit('toggle', strategy)"
        >
          <Power :size="17" />
          <span>{{ strategy.enabled ? "已启用" : "启用" }}</span>
        </button>
      </div>
    </header>

    <div class="strategy-detail-grid">
      <section class="strategy-detail-main">
        <nav class="strategy-tabs" aria-label="策略参数分组">
          <span v-for="group in paramGroups" :key="group.title">
            <component :is="group.icon" :size="16" />{{ group.title }}
          </span>
        </nav>

        <div class="strategy-param-groups">
          <section v-for="group in paramGroups" :key="group.title" class="strategy-param-group">
            <h4><component :is="group.icon" :size="17" />{{ group.title }}</h4>
            <div class="strategy-param-grid">
              <label v-for="param in group.params" :key="param.key" class="strategy-param-field">
                <span>{{ param.label }}</span>
                <div class="strategy-param-input">
                  <input
                    :value="displayParamValue(param)"
                    type="number"
                    :step="displayParamStep(param.step, param)"
                    @focus="beginParamEdit(param)"
                    @input="updateParamDraft(param, $event)"
                    @blur="commitParam(param, $event)"
                    @keydown.enter.prevent="commitOnEnter"
                  />
                  <strong>{{ param.unit }}</strong>
                </div>
                <small>{{ param.hint }}</small>
              </label>
            </div>
          </section>
        </div>
      </section>

      <aside class="strategy-detail-rail">
        <section class="strategy-rail-card safety">
          <header class="strategy-section-head compact">
            <div>
              <h3>{{ strategy.id === "intraday_macd" ? "安全硬约束" : strategy.id === "ma_atr_intraday" ? "当前规则与约束" : "策略固定规则" }}</h3>
              <p>{{ strategy.id === "intraday_macd" ? "交易安全底线锁定" : strategy.id === "ma_atr_intraday" ? "随左侧参数实时同步" : "运行时强制执行" }}</p>
            </div>
            <span v-if="strategy.id !== 'ma_atr_intraday'" class="locked"><LockKeyhole :size="13" />不可修改</span>
          </header>

          <div class="strategy-rule-groups">
            <section v-for="group in ruleGroups" :key="group.title" class="strategy-rule-group">
              <h4><component :is="group.icon" :size="17" />{{ group.title }}</h4>
              <ul>
                <li v-for="item in group.items" :key="item">{{ item }}</li>
              </ul>
            </section>
          </div>
        </section>

        <section class="strategy-rail-card">
          <h3>当前状态</h3>
          <div class="strategy-status-grid">
            <span><Activity :size="17" /><small>最近信号</small><strong>{{ strategy.last_signal || "暂无" }}</strong></span>
            <span><Clock3 :size="17" /><small>执行频率</small><strong>{{ strategy.cadence }}</strong></span>
            <span><WalletCards :size="17" /><small>覆盖市场</small><strong>{{ strategy.markets.join(" / ") }}</strong></span>
            <span><ShieldCheck :size="17" /><small>运行状态</small><strong>{{ stateLabel }}</strong></span>
          </div>
        </section>

        <section class="strategy-rail-card">
          <h3>运行监测</h3>
          <div class="strategy-monitor-list">
            <span><time>实时</time>{{ strategy.name }} 参数已载入 <b>运行中</b></span>
            <span><time>检查</time>硬约束与风控规则同步完成 <b>已通过</b></span>
            <span><time>信号</time>{{ strategy.last_signal || "等待下一次扫描" }} <b>观察中</b></span>
          </div>
          <div class="strategy-backtest-controls">
            <div class="strategy-market-switch" role="group" aria-label="回测市场">
              <button
                v-for="market in backtestMarkets"
                :key="market"
                type="button"
                :class="{ active: selectedBacktestMarket === market }"
                :disabled="backtestRunning"
                @click="selectedBacktestMarket = market"
              >
                {{ market === "HK" ? "港股" : "美股" }}
              </button>
            </div>
            <button
              class="text-button strategy-backtest"
              type="button"
              :title="`运行${selectedBacktestMarket === 'HK' ? '港股' : '美股'}回测`"
              :disabled="backtestRunning"
              @click="emit('backtest', strategy.id, selectedBacktestMarket)"
            >
              <PlayCircle :size="16" />
              <span>{{ backtestRunning ? "回测中..." : currentBacktest ? "重新回测" : "运行回测" }}</span>
            </button>
          </div>
        </section>
      </aside>
    </div>

    <section class="backtest-report-panel">
      <header class="backtest-report-head">
        <div>
          <p class="eyebrow">BACKTEST EXPORT</p>
          <h3>回测 CSV 报告</h3>
          <p>
            当前市场：{{ selectedBacktestMarket === "HK" ? "港股" : "美股" }}。股票来源：当前候选池。完成后可下载 Excel 可打开的 CSV。
          </p>
        </div>
        <a
          v-if="currentBacktest && !backtestRunning"
          class="text-button backtest-download-button"
          :href="backtestDownloadUrl"
          :download="`backtest_${currentBacktest.id}.csv`"
        >
          下载 CSV
        </a>
      </header>

      <div v-if="backtestRunning" class="backtest-progress">
        <div class="backtest-progress-copy">
          <strong>{{ backtestProgressLabel }}</strong>
          <span>{{ Math.round(backtestProgress) }}%</span>
        </div>
        <div class="backtest-progress-track">
          <i :style="{ width: `${backtestProgress}%` }" />
        </div>
        <p>正在生成交易明细：股票代码、开仓时间、平仓时间、仓位金额、数量、盈利亏损。</p>
      </div>

      <div v-else-if="backtestError" class="backtest-empty error">
        <strong>回测失败</strong>
        <span>{{ backtestError }}</span>
      </div>

      <div v-else-if="currentBacktest" class="backtest-result-panel">
        <div class="backtest-report-metrics">
          <span :class="{ gain: currentBacktest.total_return_pct >= 0, loss: currentBacktest.total_return_pct < 0 }">
            <strong>{{ signedPercent(currentBacktest.total_return_pct) }}</strong>
            <small>总收益率</small>
          </span>
          <span>
            <strong>{{ signedPercent(-currentBacktest.max_drawdown_pct) }}</strong>
            <small>最大回撤</small>
          </span>
          <span>
            <strong>{{ currentBacktest.win_rate_pct.toFixed(2) }}%</strong>
            <small>胜率</small>
          </span>
          <span>
            <strong>{{ currentBacktest.trade_rows.length || currentBacktest.trades }}</strong>
            <small>交易明细</small>
          </span>
        </div>

        <div
          v-if="currentBacktest.notes.length"
          class="backtest-note-panel"
        >
          <strong>回测诊断</strong>
          <ul>
            <li v-for="note in currentBacktest.notes" :key="note">{{ note }}</li>
          </ul>
        </div>

        <section class="backtest-trade-detail">
          <header>
            <div>
              <strong>交易明细预览</strong>
              <small>已显示 {{ visibleBacktestTrades.length }} / {{ currentBacktest.trade_rows.length }} 条</small>
            </div>
            <span>完整明细可下载 CSV</span>
          </header>

          <div v-if="visibleBacktestTrades.length" class="backtest-trade-table-wrap">
            <table class="backtest-trade-table">
              <thead>
                <tr>
                  <th>股票</th>
                  <th>方向</th>
                  <th>开仓时间</th>
                  <th>平仓时间</th>
                  <th>数量</th>
                  <th>盈利亏损</th>
                  <th>平仓原因</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="trade in visibleBacktestTrades"
                  :key="`${trade.symbol}-${trade.entry_time}-${trade.exit_time}`"
                >
                  <td><strong>{{ trade.symbol }}</strong></td>
                  <td>{{ tradeSideLabel(trade.side) }}</td>
                  <td>{{ trade.entry_time }}</td>
                  <td>{{ trade.exit_time }}</td>
                  <td>{{ trade.quantity }}</td>
                  <td :class="{ gain: trade.pnl >= 0, loss: trade.pnl < 0 }">{{ money(trade.pnl) }}</td>
                  <td class="backtest-reason-cell">{{ trade.exit_reason || "平仓原因待记录" }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-else class="backtest-empty compact">
            <strong>暂无交易明细</strong>
            <span>本次区间没有产生完整开平仓记录</span>
          </div>

          <button
            v-if="remainingTradeCount > 0"
            class="backtest-more-button"
            type="button"
            @click="visibleTradeCount += 20"
          >
            再显示 {{ Math.min(20, remainingTradeCount) }} 条
            <small>剩余 {{ remainingTradeCount }} 条</small>
          </button>
        </section>
      </div>

      <div v-else class="backtest-empty">
        <strong>尚未运行回测</strong>
        <span>点击右侧“运行回测”，完成后即可下载 CSV 明细。</span>
      </div>
    </section>
  </article>
</template>

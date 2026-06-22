<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import { PlayCircle, Power, SlidersHorizontal } from "lucide-vue-next";
import type { Market, ParamValue, StrategyConfig } from "../api/types";

const props = defineProps<{
  strategy: StrategyConfig;
}>();

const emit = defineEmits<{
  toggle: [StrategyConfig];
  updateParam: [StrategyConfig, string, ParamValue];
  backtest: [string, Market];
}>();

const paramDraft = reactive<Record<string, ParamValue>>({});

const PARAM_LABELS: Record<string, string> = {
  fast_ema: "快线 EMA",
  slow_ema: "慢线 EMA",
  signal_ema: "信号线 DEA",
  stop_loss_pct: "止损比例(%)",
  take_profit_1_pct: "第一档止盈(%)",
  take_profit_2_pct: "第二档止盈(%)",
  position_fraction_pct: "单次开仓比例(%)",
  max_positions: "最大同时持仓",
  single_position_cap_pct: "单只最大仓位(%)",
  target_positions_min: "目标持仓下限",
  target_positions_max: "目标持仓上限",
  max_symbol_drawdown_pct: "单标的最大回撤(%)",
  rebalance_months: "调仓周期(月)",
  hot_gain_block_pct: "禁买涨幅阈值(%)"
};

watch(
  () => props.strategy.params,
  (params) => {
    Object.keys(paramDraft).forEach((key) => delete paramDraft[key]);
    Object.entries(params).forEach(([key, value]) => {
      paramDraft[key] = value;
    });
  },
  { immediate: true }
);

const stateLabel = computed(() => {
  if (!props.strategy.enabled) {
    return "已暂停";
  }
  return props.strategy.state === "running" ? "运行中" : props.strategy.state;
});

function inputType(value: ParamValue) {
  return typeof value === "number" ? "number" : "text";
}

function paramLabel(key: string): string {
  return PARAM_LABELS[key] ?? key;
}

function normalize(key: string, raw: Event) {
  const target = raw.target as HTMLInputElement;
  const current = props.strategy.params[key];
  if (typeof current === "number") {
    return Number(target.value);
  }
  if (typeof current === "boolean") {
    return target.checked;
  }
  return target.value;
}
</script>

<template>
  <article class="strategy-card" :class="{ muted: !strategy.enabled }">
    <header class="strategy-head">
      <div>
        <p class="eyebrow">{{ strategy.automation === "full_auto" ? "全自动" : "半自动" }}</p>
        <h3>{{ strategy.name }}</h3>
      </div>
      <button
        class="icon-button"
        :class="{ active: strategy.enabled }"
        :title="strategy.enabled ? '暂停策略' : '开启策略'"
        @click="emit('toggle', strategy)"
      >
        <Power :size="18" />
      </button>
    </header>

    <p class="strategy-desc">{{ strategy.description }}</p>

    <div class="strategy-meta">
      <span>{{ stateLabel }}</span>
      <span>{{ strategy.cadence }}</span>
      <span>{{ strategy.markets.join(" / ") }}</span>
    </div>

    <div class="param-grid">
      <label v-for="(value, key) in strategy.params" :key="key">
        <span>{{ paramLabel(key) }}</span>
        <input
          v-model="paramDraft[key]"
          :type="inputType(value)"
          @change="emit('updateParam', strategy, key, normalize(key, $event))"
        />
      </label>
    </div>

    <div class="risk-strip">
      <SlidersHorizontal :size="15" />
      <span v-for="item in strategy.risk_controls.slice(0, 3)" :key="item">{{ item }}</span>
    </div>

    <footer class="strategy-actions">
      <span class="last-signal">{{ strategy.last_signal }}</span>
      <button class="text-button" title="运行回测" @click="emit('backtest', strategy.id, strategy.markets[0])">
        <PlayCircle :size="16" />
        <span>回测</span>
      </button>
    </footer>
  </article>
</template>




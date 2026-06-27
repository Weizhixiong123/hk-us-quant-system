<script setup lang="ts">
import { computed, reactive, watch, type Component } from "vue";
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
import type { Market, ParamValue, StrategyConfig } from "../api/types";

interface ParamDefinition {
  key: string;
  label: string;
  hint: string;
  unit: string;
  min: number;
  max: number;
  step: number;
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
}>();

const emit = defineEmits<{
  toggle: [StrategyConfig];
  updateParam: [StrategyConfig, string, ParamValue];
  backtest: [string, Market];
}>();

const paramDraft = reactive<Record<string, ParamValue>>({});

const INTRADAY_PARAM_GROUPS: ParamGroup[] = [
  {
    title: "退出与风控",
    icon: Target,
    params: [
      { key: "stop_loss_pct", label: "固定止损", hint: "亏损达到阈值后立即全部平仓", unit: "%", min: 0.1, max: 10, step: 0.1 },
      { key: "take_profit_1_pct", label: "第一档止盈", hint: "达到阈值后减仓 50%", unit: "%", min: 0.1, max: 20, step: 0.1 },
      { key: "take_profit_2_pct", label: "第二档止盈", hint: "达到阈值后全部平仓", unit: "%", min: 0.1, max: 30, step: 0.1 },
      { key: "max_daily_loss_pct", label: "单日最大亏损", hint: "触发后当日停止所有新交易", unit: "%", min: 0.5, max: 10, step: 0.1 }
    ]
  },
  {
    title: "仓位管理",
    icon: WalletCards,
    params: [
      { key: "position_fraction_pct", label: "单次开仓仓位", hint: "按账户总权益计算目标市值", unit: "%", min: 1, max: 30, step: 1 },
      { key: "max_positions", label: "最大同时持仓", hint: "日内策略允许持有的标的上限", unit: "只", min: 1, max: 10, step: 1 }
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

const INTRADAY_RULES: RuleGroup[] = [
  {
    title: "信号引擎",
    icon: BarChart3,
    items: ["15 分钟主周期", "5 分钟二次确认", "MACD 12 / 26 / 9", "价格位于 15 分钟 5MA 正确方向"]
  },
  {
    title: "盘前筛选",
    icon: Activity,
    items: ["成交额不低于 500 万", "前日振幅 2% - 8%", "股价不低于 2 元", "排除停牌、除权除息及重大公告"]
  },
  {
    title: "交易时段",
    icon: Clock3,
    items: ["开盘 30 分钟后开始开仓", "收盘前 90 分钟停止开仓", "收盘前 10 分钟强制清仓", "港股午休时段不执行信号"]
  },
  {
    title: "执行约束",
    icon: ShieldCheck,
    items: ["同一标的不重复加仓", "止损后当日禁止重开", "做空前校验可借券状态", "美股账户执行 PDT 检查"]
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
    Object.keys(paramDraft).forEach((key) => delete paramDraft[key]);
    Object.assign(paramDraft, params);
  },
  { immediate: true, deep: true }
);

const stateLabel = computed(() => {
  if (!props.strategy.enabled) {
    return "已暂停";
  }
  return props.strategy.state === "running" ? "运行中" : props.strategy.state;
});

const paramGroups = computed(() =>
  props.strategy.id === "intraday_macd" ? INTRADAY_PARAM_GROUPS : TREND_PARAM_GROUPS
);

const ruleGroups = computed(() =>
  props.strategy.id === "intraday_macd" ? INTRADAY_RULES : TREND_RULES
);

function updateParam(definition: ParamDefinition, event: Event): void {
  const target = event.target as HTMLInputElement;
  const current = props.strategy.params[definition.key];
  const value = typeof current === "number" ? Number(target.value) : target.value;
  paramDraft[definition.key] = value;
  emit("updateParam", props.strategy, definition.key, value);
}
</script>

<template>
  <article class="strategy-card" :class="{ muted: !strategy.enabled }">
    <header class="strategy-head">
      <div class="strategy-identity">
        <div class="strategy-number">{{ strategy.id === "intraday_macd" ? "01" : "02" }}</div>
        <div>
          <p class="eyebrow">{{ strategy.automation === "full_auto" ? "全自动交易" : "中长线配置" }}</p>
          <h2>{{ strategy.name }}</h2>
          <p class="strategy-desc">{{ strategy.description }}</p>
        </div>
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
          <span>{{ strategy.enabled ? "已启用" : "已停用" }}</span>
        </button>
      </div>
    </header>

    <div class="strategy-facts">
      <span><strong>执行频率</strong>{{ strategy.cadence }}</span>
      <span><strong>覆盖市场</strong>{{ strategy.markets.join(" / ") }}</span>
      <span><strong>参数保存</strong>修改后自动生效</span>
    </div>

    <div class="strategy-config-layout">
      <section class="strategy-config-panel">
        <header class="strategy-section-head">
          <div>
            <h3>运行参数</h3>
            <p>仅开放会影响仓位与退出执行的参数</p>
          </div>
          <span>可调整</span>
        </header>

        <div class="strategy-param-groups">
          <section v-for="group in paramGroups" :key="group.title" class="strategy-param-group">
            <h4><component :is="group.icon" :size="17" />{{ group.title }}</h4>
            <div class="strategy-param-grid">
              <label v-for="param in group.params" :key="param.key" class="strategy-param-field">
                <span>{{ param.label }}</span>
                <div class="strategy-param-input">
                  <input
                    :value="paramDraft[param.key]"
                    type="number"
                    :min="param.min"
                    :max="param.max"
                    :step="param.step"
                    @change="updateParam(param, $event)"
                  />
                  <strong>{{ param.unit }}</strong>
                </div>
                <small>{{ param.hint }}</small>
              </label>
            </div>
          </section>
        </div>
      </section>

      <section class="strategy-rules-panel">
        <header class="strategy-section-head">
          <div>
            <h3>策略固定规则</h3>
            <p>按策略说明锁定，运行时强制执行</p>
          </div>
          <span class="locked"><LockKeyhole :size="13" />不可修改</span>
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
    </div>

    <footer class="strategy-actions">
      <div class="last-signal">
        <span>最近信号</span>
        <strong>{{ strategy.last_signal || "暂无信号" }}</strong>
      </div>
      <button class="text-button" type="button" title="运行回测" @click="emit('backtest', strategy.id, strategy.markets[0])">
        <PlayCircle :size="16" />
        <span>运行回测</span>
      </button>
    </footer>
  </article>
</template>

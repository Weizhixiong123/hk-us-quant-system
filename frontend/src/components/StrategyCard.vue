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
    title: "MACD 信号",
    icon: BarChart3,
    params: [
      { key: "fast_ema", label: "快线周期", hint: "三周期信号共同使用的 MACD 快线", unit: "根", min: 2, max: 60, step: 1 },
      { key: "slow_ema", label: "慢线周期", hint: "必须大于快线周期", unit: "根", min: 3, max: 120, step: 1 },
      { key: "signal_ema", label: "信号线周期", hint: "MACD DEA 平滑周期", unit: "根", min: 2, max: 60, step: 1 }
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
      { key: "min_turnover", label: "最低日均成交额", hint: "过滤流动性不足的标的", unit: "元", min: 0, max: 10000000000, step: 100000 },
      { key: "min_amplitude_pct", label: "前日振幅下限", hint: "前一交易日振幅最小值", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "max_amplitude_pct", label: "前日振幅上限", hint: "必须不小于振幅下限", unit: "%", min: 0, max: 100, step: 0.5 },
      { key: "min_price", label: "最低股价", hint: "过滤价格过低的标的", unit: "元", min: 0, max: 100000, step: 0.5 },
      { key: "min_turnover_rate", label: "最低换手率", hint: "按成交额与总市值计算", unit: "%", min: 0, max: 100, step: 0.1 }
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

const INTRADAY_RULES: RuleGroup[] = [
  {
    title: "信号引擎",
    icon: BarChart3,
    items: ["15 / 5 / 3 分钟三周期共振", "三周期柱同向抬高开多、走低开空", "持仓柱体反向同步即全平", "进出场按 3 分钟收线评估"]
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
            <p>{{ strategy.id === "intraday_macd" ? "修改后立即生效，并在项目重启后保留" : "修改后自动应用到策略运行" }}</p>
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
            <h3>{{ strategy.id === "intraday_macd" ? "安全硬约束" : "策略固定规则" }}</h3>
            <p>{{ strategy.id === "intraday_macd" ? "交易安全底线锁定，运行时强制执行" : "按策略说明锁定，运行时强制执行" }}</p>
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

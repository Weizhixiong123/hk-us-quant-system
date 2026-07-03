<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  Building2,
  CheckCircle2,
  Clock3,
  Link2,
  PlayCircle,
  ShieldCheck,
  UserRound
} from "lucide-vue-next";
import { fetchLiveSettings, reloadRuntime, saveLiveSettings } from "../api/client";
import type {
  FutuTradeEnv,
  LiveBroker,
  Market,
  LiveSettingsSnapshot,
  LiveSettingsUpdate,
  TigerTradeEnv
} from "../api/types";

type RuntimeMode = "dry_run" | "sandbox" | "live";
type LiveSettingsForm = Omit<LiveSettingsSnapshot, "intraday_params">;

const loading = ref(false);
const applying = ref(false);
const message = ref("");
const error = ref("");
const privateKeyDraft = ref("");
const clearPrivateKey = ref(false);

const form = reactive<LiveSettingsForm>({
  runtime: {
    enabled: false,
    dry_run: true,
    broker: "futu",
    poll_interval_seconds: 2,
    default_equity: 1_000_000
  },
  futu: {
    host: "127.0.0.1",
    port: 11111,
    trd_env: "SIMULATE",
    market: "HK",
    markets: ["HK", "US"],
    real_trading_confirmed: false
  },
  tiger: {
    tiger_id: "",
    account: "",
    private_key_path: "",
    tiger_public_key_path: "",
    private_key_configured: false,
    environment: "sandbox",
    language: "zh_CN",
    max_contracts: 100,
    use_preset_contracts: false,
    market: "US",
    markets: ["US"],
    live_trading_confirmed: false
  },
  safety: {
    operator_note: ""
  },
  intraday_universe: {
    selection_mode: "auto",
    manual_symbols: []
  },
  saved_at: "",
  restart_required: true
});

const runtimeMode = computed<RuntimeMode>(() => {
  if (form.runtime.dry_run) {
    return "dry_run";
  }
  if (form.runtime.broker === "futu") {
    return form.futu.trd_env === "REAL" ? "live" : "sandbox";
  }
  return form.tiger.environment === "live" ? "live" : "sandbox";
});

const activeBrokerLabel = computed(() => (form.runtime.broker === "futu" ? "富途" : "老虎"));
const runtimeModeLabel = computed(() => {
  switch (runtimeMode.value) {
    case "dry_run":
      return "干跑";
    case "sandbox":
      return "模拟盘";
    case "live":
      return "实盘";
  }
});
const brokerEnvironmentLabel = computed(() => {
  if (runtimeMode.value === "dry_run") {
    return "不连接券商";
  }
  return runtimeMode.value === "live" ? "实盘" : "模拟盘";
});
const brokerEnvironmentDetail = computed(() => {
  if (form.runtime.broker === "futu") {
    if (runtimeMode.value === "dry_run") {
      return "富途环境保持 SIMULATE，运行时不触达券商";
    }
    return runtimeMode.value === "live" ? "富途底层环境：REAL" : "富途底层环境：SIMULATE";
  }
  if (runtimeMode.value === "dry_run") {
    return "老虎环境保持 sandbox，运行时不触达券商";
  }
  return runtimeMode.value === "live" ? "老虎底层环境：live" : "老虎底层环境：sandbox";
});
const usesDefaultEquity = computed(() => runtimeMode.value === "dry_run");

function applySnapshot(snapshot: LiveSettingsSnapshot): void {
  Object.assign(form.runtime, snapshot.runtime);
  Object.assign(form.futu, snapshot.futu);
  Object.assign(form.tiger, snapshot.tiger);
  Object.assign(form.safety, snapshot.safety);
  Object.assign(form.intraday_universe, snapshot.intraday_universe);
  form.saved_at = snapshot.saved_at;
  form.restart_required = snapshot.restart_required;
}

async function loadSettings(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    applySnapshot(await fetchLiveSettings());
  } catch (err) {
    error.value = err instanceof Error ? err.message : "配置加载失败";
  } finally {
    loading.value = false;
  }
}

function setBroker(value: LiveBroker): void {
  error.value = "";
  message.value = "";
  const currentMode = runtimeMode.value;
  form.runtime.broker = value;
  setRuntimeMode(currentMode);
}

function setRuntimeMode(value: RuntimeMode): void {
  error.value = "";
  message.value = "";
  form.runtime.dry_run = value === "dry_run";
  if (form.runtime.broker === "futu") {
    form.futu.trd_env = (value === "live" ? "REAL" : "SIMULATE") as FutuTradeEnv;
  } else {
    form.tiger.environment = (value === "live" ? "live" : "sandbox") as TigerTradeEnv;
  }
}

function buildPayload(): LiveSettingsUpdate {
  const payload: LiveSettingsUpdate = {
    runtime: { ...form.runtime, enabled: true },
    futu: {
      ...form.futu,
      market: form.futu.markets[0] ?? "HK"
    },
    tiger: {
      tiger_id: form.tiger.tiger_id,
      account: form.tiger.account,
      private_key_path: form.tiger.private_key_path,
      tiger_public_key_path: form.tiger.tiger_public_key_path,
      environment: form.tiger.environment,
      language: form.tiger.language,
      max_contracts: Number(form.tiger.max_contracts),
      use_preset_contracts: form.tiger.use_preset_contracts,
      market: form.tiger.markets[0] ?? "US",
      markets: form.tiger.markets
    },
    safety: {
      operator_note: form.safety.operator_note
    }
  };

  if (privateKeyDraft.value.trim()) {
    payload.tiger = {
      ...payload.tiger,
      private_key: privateKeyDraft.value
    };
  }
  if (clearPrivateKey.value) {
    payload.tiger = {
      ...payload.tiger,
      clear_private_key: true
    };
  }
  return payload;
}

function toggleMarket(markets: Market[], market: Market): void {
  const index = markets.indexOf(market);
  if (index >= 0) {
    if (markets.length > 1) {
      markets.splice(index, 1);
    }
    return;
  }
  markets.push(market);
}

async function applySettings(): Promise<void> {
  applying.value = true;
  error.value = "";
  message.value = "";
  try {
    applySnapshot(await saveLiveSettings(buildPayload()));
    privateKeyDraft.value = "";
    clearPrivateKey.value = false;
    const result = await reloadRuntime();
    if (result.ok) {
      message.value = result.runtime_running
        ? `配置已应用：${result.runtime_dry_run ? "干跑模式" : `${activeBrokerLabel.value}已连接`}`
        : "配置已应用";
    } else {
      error.value = `应用失败：${result.error ?? "未知错误"}`;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "应用配置失败";
  } finally {
    applying.value = false;
  }
}

function savedAt(value: string): string {
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

onMounted(loadSettings);
</script>

<template>
  <section class="settings-page">
    <section class="settings-overview" aria-label="实盘配置概览">
      <article class="panel settings-overview-card intro-card">
        <div class="settings-icon">
          <UserRound :size="26" />
        </div>
        <div>
          <p class="eyebrow">LIVE CONFIG</p>
          <h2>客户实盘配置</h2>
          <span>当前配置正在生效</span>
        </div>
      </article>

      <article class="panel settings-overview-card">
        <div class="settings-icon">
          <Building2 :size="26" />
        </div>
        <div>
          <span>当前账户</span>
          <strong>{{ activeBrokerLabel }} · {{ runtimeModeLabel }}</strong>
          <small class="status-pill active">
            <CheckCircle2 :size="13" />
            应用后自动运行
          </small>
        </div>
      </article>

      <article class="panel settings-overview-card">
        <div class="settings-icon">
          <Clock3 :size="26" />
        </div>
        <div>
          <span>最近保存</span>
          <strong>{{ savedAt(form.saved_at) }}</strong>
          <small>手动保存</small>
        </div>
      </article>

      <article class="panel settings-overview-card">
        <div class="settings-icon">
          <ShieldCheck :size="26" />
        </div>
        <div>
          <span>当前模式</span>
          <strong :class="runtimeMode === 'live' ? 'danger-text' : 'ok-text'">
            {{ runtimeMode === "live" ? "实盘" : "非实盘" }}
          </strong>
          <small>{{ runtimeMode === "live" ? "应用后直接连接券商" : "安全模式" }}</small>
        </div>
      </article>
    </section>

    <p v-if="message" class="success-bar settings-message">{{ message }}</p>
    <p v-if="error" class="error-bar settings-message">{{ error }}</p>

    <section class="settings-workspace">
      <article class="panel settings-card runtime-card">
        <header class="settings-card-head">
          <div class="settings-heading">
            <div class="settings-icon small">
              <PlayCircle :size="24" />
            </div>
            <div>
              <h2>运行控制</h2>
              <p>配置自动交易运行方式</p>
            </div>
          </div>
        </header>

        <div class="field-group">
          <span class="field-title">交易平台</span>
          <div class="segmented broker-segmented">
            <button
              type="button"
              :class="{ active: form.runtime.broker === 'futu' }"
              @click="setBroker('futu')"
            >
              富途
            </button>
            <button
              type="button"
              :class="{ active: form.runtime.broker === 'tiger' }"
              @click="setBroker('tiger')"
            >
              老虎
            </button>
          </div>
        </div>

        <div class="field-group">
          <span class="field-title">运行模式</span>
          <div class="segmented mode-segmented">
            <button
              type="button"
              :class="{ active: runtimeMode === 'dry_run' }"
              @click="setRuntimeMode('dry_run')"
            >
              干跑
            </button>
            <button
              type="button"
              :class="{ active: runtimeMode === 'sandbox' }"
              @click="setRuntimeMode('sandbox')"
            >
              模拟盘
            </button>
            <button
              type="button"
              class="danger-tab"
              :class="{ active: runtimeMode === 'live' }"
              @click="setRuntimeMode('live')"
            >
              实盘
            </button>
          </div>
        </div>

        <div class="settings-form" :class="{ 'two-col': usesDefaultEquity }">
          <label>
            <span>轮询间隔 / 秒</span>
            <input v-model.number="form.runtime.poll_interval_seconds" type="number" min="0.5" step="0.5" />
          </label>
          <label v-if="usesDefaultEquity">
            <span>干跑账户权益</span>
            <input v-model.number="form.runtime.default_equity" type="number" min="1" step="1000" />
          </label>
        </div>
      </article>

      <article v-if="form.runtime.broker === 'futu'" class="panel settings-card broker-card">
        <header class="settings-card-head">
          <div class="settings-heading">
            <div class="settings-icon small">
              <Link2 :size="24" />
            </div>
            <div>
              <h2>富途连接</h2>
              <p>配置富途开放平台连接信息</p>
            </div>
          </div>
          <Link2 :size="19" />
        </header>

        <div class="settings-form two-col">
          <label>
            <span>Host</span>
            <input v-model.trim="form.futu.host" />
          </label>
          <label>
            <span>Port</span>
            <input v-model.number="form.futu.port" type="number" min="1" />
          </label>
          <label>
            <span>交易环境</span>
            <div class="locked-env" :class="{ danger: runtimeMode === 'live' }">
              <strong>{{ brokerEnvironmentLabel }}</strong>
              <small>{{ brokerEnvironmentDetail }}</small>
            </div>
          </label>
          <label>
            <span>交易市场</span>
            <div class="market-checks">
              <button
                type="button"
                :class="{ active: form.futu.markets.includes('HK') }"
                @click="toggleMarket(form.futu.markets, 'HK')"
              >
                港股
              </button>
              <button
                type="button"
                :class="{ active: form.futu.markets.includes('US') }"
                @click="toggleMarket(form.futu.markets, 'US')"
              >
                美股
              </button>
            </div>
          </label>
        </div>

        <div class="connection-note">
          <ShieldCheck :size="28" />
          <div>
            <strong>连接状态</strong>
            <span>{{ runtimeMode === "dry_run" ? "干跑模式不连接券商" : "应用后自动连接 FutuOpenD" }}</span>
          </div>
          <i />
        </div>
      </article>

      <article v-else class="panel settings-card broker-card">
        <header class="settings-card-head">
          <div class="settings-heading">
            <div class="settings-icon small">
              <Link2 :size="24" />
            </div>
            <div>
              <h2>老虎连接</h2>
              <p>配置老虎证券开放平台连接信息</p>
            </div>
          </div>
          <Link2 :size="19" />
        </header>

        <div class="settings-form two-col">
          <label>
            <span>Tiger ID</span>
            <input v-model.trim="form.tiger.tiger_id" autocomplete="off" />
          </label>
          <label>
            <span>账户号</span>
            <input v-model.trim="form.tiger.account" autocomplete="off" />
          </label>
          <label>
            <span>私钥文件路径</span>
            <input v-model.trim="form.tiger.private_key_path" autocomplete="off" />
          </label>
          <label>
            <span>老虎公钥路径</span>
            <input v-model.trim="form.tiger.tiger_public_key_path" autocomplete="off" />
          </label>
          <label>
            <span>私钥内容</span>
            <textarea v-model="privateKeyDraft" rows="4" autocomplete="off" />
            <small>{{ form.tiger.private_key_configured ? "已配置，留空则保持不变" : "未配置，推荐使用文件路径" }}</small>
          </label>
          <label class="switch-row key-clear">
            <input v-model="clearPrivateKey" type="checkbox" />
            <span>清除已保存私钥内容</span>
          </label>
          <label>
            <span>交易环境</span>
            <div class="locked-env" :class="{ danger: runtimeMode === 'live' }">
              <strong>{{ brokerEnvironmentLabel }}</strong>
              <small>{{ brokerEnvironmentDetail }}</small>
            </div>
          </label>
          <label>
            <span>交易市场</span>
            <div class="market-checks">
              <button
                type="button"
                :class="{ active: form.tiger.markets.includes('US') }"
                @click="toggleMarket(form.tiger.markets, 'US')"
              >
                美股
              </button>
              <button
                type="button"
                :class="{ active: form.tiger.markets.includes('HK') }"
                @click="toggleMarket(form.tiger.markets, 'HK')"
              >
                港股
              </button>
            </div>
          </label>
          <label>
            <span>语言</span>
            <input v-model.trim="form.tiger.language" />
          </label>
          <label>
            <span>最大合约数</span>
            <input v-model.number="form.tiger.max_contracts" type="number" min="1" />
          </label>
          <label class="switch-row key-clear">
            <input v-model="form.tiger.use_preset_contracts" type="checkbox" />
            <span>使用预设合约</span>
          </label>
        </div>

        <div class="connection-note">
          <ShieldCheck :size="28" />
          <div>
            <strong>连接状态</strong>
            <span>{{ runtimeMode === "dry_run" ? "干跑模式不连接券商" : "应用后自动连接老虎网关" }}</span>
          </div>
          <i />
        </div>
      </article>

      <article class="panel settings-apply-card">
        <div class="settings-apply-copy">
          <div class="settings-icon small"><CheckCircle2 :size="24" /></div>
          <div>
            <h2>应用当前配置</h2>
            <p>保存全部字段并立即按 {{ activeBrokerLabel }} · {{ runtimeModeLabel }} 模式运行。</p>
          </div>
        </div>
        <div class="settings-apply-summary">
          <span><strong>交易平台</strong>{{ activeBrokerLabel }}</span>
          <span><strong>运行模式</strong>{{ runtimeModeLabel }}</span>
          <span><strong>覆盖市场</strong>{{ (form.runtime.broker === "futu" ? form.futu.markets : form.tiger.markets).join(" / ") }}</span>
        </div>
        <button class="save-button" type="button" :disabled="applying || loading" @click="applySettings">
          <CheckCircle2 :size="22" />
          <span>{{ applying ? "应用中" : "应用配置" }}</span>
        </button>
      </article>
    </section>
  </section>
</template>

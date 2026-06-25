<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  PlayCircle,
  Save,
  ServerCog,
  ShieldCheck
} from "lucide-vue-next";
import { fetchLiveSettings, saveLiveSettings } from "../api/client";
import type {
  FutuTradeEnv,
  LiveBroker,
  LiveSettingsSnapshot,
  LiveSettingsUpdate,
  TigerTradeEnv
} from "../api/types";

type RuntimeMode = "dry_run" | "sandbox" | "live";

const LIVE_ACK = "我确认启用实盘交易";

const loading = ref(false);
const saving = ref(false);
const message = ref("");
const error = ref("");
const privateKeyDraft = ref("");
const clearPrivateKey = ref(false);
const liveAck = ref("");

const form = reactive<LiveSettingsSnapshot>({
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
    live_trading_confirmed: false
  },
  safety: {
    pause_new_orders: false,
    close_only: false,
    operator_note: ""
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
const liveAlreadyConfirmed = computed(() =>
  form.runtime.broker === "futu"
    ? form.futu.real_trading_confirmed
    : form.tiger.live_trading_confirmed
);
const liveAckReady = computed(() => liveAlreadyConfirmed.value || liveAck.value.trim() === LIVE_ACK);
const canSave = computed(() => runtimeMode.value !== "live" || liveAckReady.value);

function applySnapshot(snapshot: LiveSettingsSnapshot): void {
  Object.assign(form.runtime, snapshot.runtime);
  Object.assign(form.futu, snapshot.futu);
  Object.assign(form.tiger, snapshot.tiger);
  Object.assign(form.safety, snapshot.safety);
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
  form.runtime.broker = value;
}

function setRuntimeMode(value: RuntimeMode): void {
  form.runtime.dry_run = value === "dry_run";
  if (form.runtime.broker === "futu") {
    form.futu.trd_env = (value === "live" ? "REAL" : "SIMULATE") as FutuTradeEnv;
  } else {
    form.tiger.environment = (value === "live" ? "live" : "sandbox") as TigerTradeEnv;
  }
}

function buildPayload(): LiveSettingsUpdate {
  const payload: LiveSettingsUpdate = {
    runtime: { ...form.runtime },
    futu: {
      ...form.futu,
      real_trading_confirmed:
        form.futu.trd_env === "REAL" ? liveAckReady.value : false
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
      market: form.tiger.market,
      live_trading_confirmed:
        form.tiger.environment === "live" ? liveAckReady.value : false
    },
    safety: { ...form.safety }
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

async function saveSettings(): Promise<void> {
  if (!canSave.value) {
    error.value = `请输入“${LIVE_ACK}”`;
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    applySnapshot(await saveLiveSettings(buildPayload()));
    privateKeyDraft.value = "";
    clearPrivateKey.value = false;
    liveAck.value = "";
    message.value = "配置已保存，重启后端后生效";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "配置保存失败";
  } finally {
    saving.value = false;
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
  <section class="settings-layout">
    <article class="panel settings-hero">
      <header class="panel-title">
        <div>
          <p class="eyebrow">LIVE CONFIG</p>
          <h2>客户实盘配置</h2>
        </div>
        <ServerCog :size="20" />
      </header>

      <div class="settings-status">
        <div>
          <strong>{{ activeBrokerLabel }} · {{ runtimeMode }}</strong>
          <span>{{ form.runtime.enabled ? "运行时已启用" : "运行时未启用" }}</span>
        </div>
        <div>
          <strong>{{ savedAt(form.saved_at) }}</strong>
          <span>最近保存</span>
        </div>
        <div :class="runtimeMode === 'live' ? 'danger' : 'ok'">
          <strong>{{ runtimeMode === "live" ? "实盘" : "非实盘" }}</strong>
          <span>{{ runtimeMode === "live" ? "需要客户确认" : "安全模式" }}</span>
        </div>
      </div>

      <p v-if="message" class="success-bar">{{ message }}</p>
      <p v-if="error" class="error-bar">{{ error }}</p>
    </article>

    <article class="panel settings-section">
      <header class="panel-title">
        <div>
          <p class="eyebrow">RUNTIME</p>
          <h2>运行控制</h2>
        </div>
        <PlayCircle :size="19" />
      </header>

      <div class="setting-row">
        <label class="switch-row">
          <input v-model="form.runtime.enabled" type="checkbox" />
          <span>启用后台运行时</span>
        </label>
        <label class="switch-row">
          <input v-model="form.safety.close_only" type="checkbox" />
          <span>只允许平仓</span>
        </label>
        <label class="switch-row">
          <input v-model="form.safety.pause_new_orders" type="checkbox" />
          <span>暂停新开仓</span>
        </label>
      </div>

      <div class="segmented">
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

      <div class="segmented">
        <button
          type="button"
          :class="{ active: runtimeMode === 'dry_run' }"
          @click="setRuntimeMode('dry_run')"
        >
          Dry-run
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

      <div class="settings-form two-col">
        <label>
          <span>轮询间隔 / 秒</span>
          <input v-model.number="form.runtime.poll_interval_seconds" type="number" min="0.5" step="0.5" />
        </label>
        <label>
          <span>默认账户权益</span>
          <input v-model.number="form.runtime.default_equity" type="number" min="1" step="1000" />
        </label>
      </div>
    </article>

    <article v-if="form.runtime.broker === 'futu'" class="panel settings-section">
      <header class="panel-title">
        <div>
          <p class="eyebrow">FUTU</p>
          <h2>富途连接</h2>
        </div>
        <KeyRound :size="19" />
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
          <select v-model="form.futu.trd_env">
            <option value="SIMULATE">SIMULATE</option>
            <option value="REAL">REAL</option>
          </select>
        </label>
        <label>
          <span>默认市场</span>
          <select v-model="form.futu.market">
            <option value="HK">HK</option>
            <option value="US">US</option>
          </select>
        </label>
      </div>
    </article>

    <article v-else class="panel settings-section">
      <header class="panel-title">
        <div>
          <p class="eyebrow">TIGER</p>
          <h2>老虎连接</h2>
        </div>
        <KeyRound :size="19" />
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
          <select v-model="form.tiger.environment">
            <option value="sandbox">sandbox</option>
            <option value="live">live</option>
          </select>
        </label>
        <label>
          <span>默认市场</span>
          <select v-model="form.tiger.market">
            <option value="US">US</option>
            <option value="HK">HK</option>
          </select>
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
    </article>

    <article class="panel settings-section">
      <header class="panel-title">
        <div>
          <p class="eyebrow">SAFETY</p>
          <h2>实盘确认</h2>
        </div>
        <ShieldCheck :size="19" />
      </header>

      <div class="live-ack" :class="{ armed: runtimeMode === 'live' }">
        <AlertTriangle :size="18" />
        <div>
          <strong>{{ runtimeMode === "live" ? "实盘模式待确认" : "当前不触发实盘确认" }}</strong>
          <span>启用实盘前由客户本人输入确认短语。</span>
        </div>
      </div>

      <label class="ack-input">
        <span>确认短语</span>
        <input v-model="liveAck" :placeholder="LIVE_ACK" />
      </label>

      <label class="ack-input">
        <span>操作备注</span>
        <textarea v-model="form.safety.operator_note" rows="3" />
      </label>

      <button class="save-button" type="button" :disabled="saving || loading || !canSave" @click="saveSettings">
        <Save :size="18" />
        <span>{{ saving ? "保存中" : "保存配置" }}</span>
      </button>

      <div class="settings-foot">
        <CheckCircle2 :size="16" />
        <span>保存后重启后端，运行时会按此配置连接 {{ activeBrokerLabel }}。</span>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { AlertTriangle, Check, Crosshair, Plus, RefreshCw, Trash2 } from "lucide-vue-next";
import { fetchLiveSettings, fetchSymbolName, reloadRuntime, saveLiveSettings } from "../api/client";
import type { IntradayUniverseSettings, ManualSymbol, Market } from "../api/types";
import { lookupSymbolName } from "../utils/symbolLookup";

const emit = defineEmits<{ saved: [] }>();

const universe = reactive<IntradayUniverseSettings>({
  selection_mode: "auto",
  manual_symbols: []
});
const draft = reactive<ManualSymbol>({
  symbol: "",
  name: "",
  market: "US",
  shortable: false
});
const loading = ref(false);
const saving = ref(false);
const message = ref("");
const error = ref("");
/** 用户是否手动改过 / 聚焦过 name 字段 —— 一旦是,自动回填就不再覆盖 */
const nameTouched = ref(false);
const resolvingName = ref(false);
let nameLookupTimer: ReturnType<typeof setTimeout> | undefined;
let nameLookupVersion = 0;

const manualCountLabel = computed(() => `${universe.manual_symbols.length} 只标的`);

function applyUniverse(value: IntradayUniverseSettings): void {
  universe.selection_mode = "manual";
  universe.manual_symbols = value.manual_symbols.map((item) => {
    // name 缺失或为占位(等于 symbol)时,尝试用静态映射回填
    const needsLookup = !item.name || item.name.trim() === "" || item.name.trim() === item.symbol;
    if (!needsLookup) return { ...item };
    const name = lookupSymbolName(item.symbol, item.market);
    return { ...item, name: name ?? item.name };
  });
}

async function loadUniverse(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    applyUniverse((await fetchLiveSettings()).intraday_universe);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "股票池加载失败";
  } finally {
    loading.value = false;
  }
}

async function resolveName(symbol: string, market: Market): Promise<string | null> {
  const localName = lookupSymbolName(symbol, market);
  if (localName) return localName;
  try {
    return (await fetchSymbolName(symbol, market)).name;
  } catch {
    return null;
  }
}

async function addSymbol(): Promise<void> {
  message.value = "";
  error.value = "";
  const market = draft.market;
  const symbol = normalizeSymbol(draft.symbol, market);
  if (!symbol) {
    error.value = "请输入有效股票代码";
    return;
  }
  if (universe.manual_symbols.some((item) => item.symbol === symbol && item.market === draft.market)) {
    error.value = `${symbol} 已在手动股票池中`;
    return;
  }
  let name = draft.name.trim();
  if (!name) {
    resolvingName.value = true;
    name = (await resolveName(symbol, market)) ?? "";
    resolvingName.value = false;
  }
  if (!name) {
    error.value = `未找到 ${symbol} 的股票名称，请检查代码或手工填写名称`;
    return;
  }
  universe.manual_symbols.push({
    symbol,
    name,
    market,
    shortable: draft.shortable
  });
  nameLookupVersion += 1;
  clearTimeout(nameLookupTimer);
  draft.symbol = "";
  draft.name = "";
  draft.shortable = false;
  nameTouched.value = false;
}

function removeSymbol(index: number): void {
  universe.manual_symbols.splice(index, 1);
  message.value = "";
}

async function saveUniverse(): Promise<void> {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    const snapshot = await saveLiveSettings({
      intraday_universe: {
        selection_mode: "manual",
        manual_symbols: universe.manual_symbols.map((item) => ({ ...item }))
      }
    });
    applyUniverse(snapshot.intraday_universe);
    const result = await reloadRuntime();
    if (!result.ok) {
      error.value = `股票池已保存，但运行时重载失败：${result.error ?? "未知错误"}`;
      return;
    }
    message.value = `候选池已生效：手动 ${universe.manual_symbols.length} 只，并叠加自动筛选`;
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "股票池保存失败";
  } finally {
    saving.value = false;
  }
}

function normalizeSymbol(value: string, market: Market): string {
  let symbol = value.trim().toUpperCase().replace(/\s+/g, "");
  if (!/^[A-Z0-9][A-Z0-9.-]*$/.test(symbol)) {
    return "";
  }
  if (market === "HK") {
    symbol = symbol.replace(/^HK\./, "").replace(/\.HK$/, "");
    if (/^\d+$/.test(symbol)) {
      symbol = (symbol.replace(/^0+/, "") || "0").padStart(4, "0");
    }
    return `${symbol}.HK`;
  }
  return symbol.replace(/\.US$/, "");
}

onMounted(loadUniverse);

/**
 * 输入代码 + 选择市场 → 自动回填 name。
 * 设计:
 *  - 先查常用标的本地映射,未命中再查后端行情源
 *  - 用户尚未碰过 name 才回填;聚焦或手动改过就跳过
 *  - 查不到时名称留空,加入股票池前要求检查代码或手工填写
 */
watch(
  () => [draft.symbol, draft.market] as const,
  ([symbol, market]) => {
    const version = ++nameLookupVersion;
    clearTimeout(nameLookupTimer);
    resolvingName.value = false;
    if (nameTouched.value) return;
    const trimmed = symbol.trim();
    if (!trimmed) {
      draft.name = "";
      return;
    }
    const name = lookupSymbolName(trimmed, market);
    if (name) {
      draft.name = name;
      return;
    }
    draft.name = "";
    const normalized = normalizeSymbol(trimmed, market);
    if (!normalized) return;
    nameLookupTimer = setTimeout(async () => {
      resolvingName.value = true;
      const remoteName = await resolveName(normalized, market);
      if (version !== nameLookupVersion) return;
      resolvingName.value = false;
      if (nameTouched.value) return;
      draft.name = remoteName ?? "";
    }, 300);
  }
);

</script>

<template>
  <article class="manual-universe-panel">
    <header class="universe-head">
      <div class="universe-title">
        <span class="target-mark"><Crosshair :size="22" /></span>
        <div>
          <div class="eyebrow">INTRADAY UNIVERSE</div>
          <h2>日内候选池</h2>
          <p>手动股票和自动筛选会汇总进入MACD信号监控，不会直接触发下单。</p>
        </div>
      </div>
      <button class="reload-button" type="button" :disabled="loading || saving" @click="loadUniverse">
        <RefreshCw :size="15" :class="{ spinning: loading }" />
        重新读取
      </button>
    </header>

    <div class="universe-summary">
      <strong>当前候选池 = 手动候选 + 自动筛选</strong>
      <span>{{ manualCountLabel }} · 到达对应市场时自动叠加盘前筛选结果</span>
    </div>

    <div class="manual-workbench">
      <div class="symbol-form" @keydown.enter.prevent="addSymbol">
        <label>
          <span>股票代码</span>
          <input v-model.trim="draft.symbol" placeholder="AAPL / 0700" autocomplete="off" />
        </label>
        <label>
          <span>名称 <small>选填</small></span>
          <input
            v-model.trim="draft.name"
            :placeholder="resolvingName ? '正在查询…' : 'Apple / 腾讯控股'"
            autocomplete="off"
            @focus="nameTouched = true"
            @input="nameTouched = true"
          />
        </label>
        <label>
          <span>市场</span>
          <select v-model="draft.market">
            <option value="US">美股 US</option>
            <option value="HK">港股 HK</option>
          </select>
        </label>
        <label class="shortable-check">
          <input v-model="draft.shortable" type="checkbox" />
          <span>允许做空</span>
        </label>
        <button class="add-symbol" type="button" :disabled="resolvingName" @click="addSymbol">
          <Plus :size="18" />
          加入手动候选
        </button>
      </div>

      <div class="symbol-ledger">
        <div v-if="universe.manual_symbols.length === 0" class="empty-ledger">
          <Crosshair :size="28" />
          <div>
            <strong>暂无手动候选</strong>
            <span>未添加手动股票时，候选池仍会使用自动筛选结果。</span>
          </div>
        </div>
        <div v-for="(item, index) in universe.manual_symbols" :key="`${item.market}:${item.symbol}`" class="symbol-ticket">
          <span class="market-code" :class="item.market.toLowerCase()">{{ item.market }}</span>
          <div>
            <strong>{{ item.symbol }}</strong>
            <small>{{ item.name }}</small>
          </div>
          <span v-if="item.shortable" class="short-chip">可做空</span>
          <button type="button" :aria-label="`删除 ${item.symbol}`" @click="removeSymbol(index)">
            <Trash2 :size="16" />
          </button>
        </div>
      </div>

      <div class="manual-note">
        <AlertTriangle :size="17" />
        <span>手动候选会直接进入当前市场候选池，并与自动筛选结果合并；开仓仍需三周期MACD同步并通过仓位、日亏损、PDT及做空校验。</span>
      </div>
    </div>

    <footer class="universe-actions">
      <span v-if="message" class="save-message"><Check :size="15" />{{ message }}</span>
      <span v-else-if="error" class="save-error"><AlertTriangle :size="15" />{{ error }}</span>
      <span v-else>修改后需应用，运行时会自动重载。</span>
      <button type="button" :disabled="loading || saving" @click="saveUniverse">
        <Check :size="17" />
        {{ saving ? "应用中…" : "应用选股设置" }}
      </button>
    </footer>
  </article>
</template>

<style scoped>
.manual-universe-panel {
  overflow: hidden;
  border: 1px solid rgba(24, 32, 31, 0.12);
  border-radius: 8px;
  background:
    linear-gradient(115deg, rgba(21, 155, 141, 0.08), transparent 38%),
    rgba(255, 255, 255, 0.88);
  box-shadow: 0 14px 38px rgba(24, 32, 31, 0.09);
}

.universe-head,
.universe-actions,
.universe-title,
.reload-button,
.add-symbol,
.manual-note,
.save-message,
.save-error {
  display: flex;
  align-items: center;
}

.universe-head {
  justify-content: space-between;
  gap: 18px;
  padding: 18px;
}

.universe-title {
  gap: 13px;
}

.target-mark {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  border: 1px solid rgba(21, 155, 141, 0.28);
  border-radius: 7px;
  color: var(--accent-dark);
  background: rgba(21, 155, 141, 0.1);
}

.eyebrow {
  margin-bottom: 3px;
  color: var(--accent-dark);
  font-family: "IBM Plex Mono", "Cascadia Code", monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

h2,
p {
  margin: 0;
}

h2 {
  font-size: 19px;
}

p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.reload-button {
  gap: 7px;
  min-height: 36px;
  padding: 0 11px;
  border: 1px solid rgba(24, 32, 31, 0.12);
  border-radius: 6px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.7);
  font-weight: 800;
}

.universe-summary {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 18px;
  border-top: 1px solid rgba(24, 32, 31, 0.08);
  border-bottom: 1px solid rgba(24, 32, 31, 0.08);
  color: white;
  background: linear-gradient(120deg, var(--accent-dark), var(--accent));
}

.universe-summary strong {
  font-size: 14px;
}

.universe-summary span {
  color: rgba(255, 255, 255, 0.78);
  font-size: 11px;
  font-weight: 800;
}

.manual-workbench {
  padding: 16px 18px 0;
}

.symbol-form {
  display: grid;
  grid-template-columns: 1.25fr 1.35fr 0.8fr auto auto;
  gap: 10px;
  align-items: end;
}

.symbol-form label {
  display: grid;
  gap: 6px;
}

.symbol-form label > span {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
}

.symbol-form small {
  font-weight: 500;
}

.symbol-form input:not([type="checkbox"]),
.symbol-form select {
  width: 100%;
  height: 40px;
  padding: 0 11px;
  border: 1px solid rgba(24, 32, 31, 0.14);
  border-radius: 6px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.9);
  outline: none;
}

.symbol-form input:focus,
.symbol-form select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(21, 155, 141, 0.1);
}

.shortable-check {
  display: flex !important;
  align-items: center;
  gap: 7px !important;
  height: 40px;
  white-space: nowrap;
}

.shortable-check input {
  accent-color: var(--accent-dark);
}

.add-symbol {
  justify-content: center;
  gap: 7px;
  height: 40px;
  padding: 0 14px;
  border: 0;
  border-radius: 6px;
  color: white;
  background: var(--ink);
  font-weight: 800;
  white-space: nowrap;
}

.symbol-ledger {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 13px;
}

.symbol-ticket,
.empty-ledger {
  min-height: 58px;
  border: 1px solid rgba(24, 32, 31, 0.09);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.72);
}

.symbol-ticket {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 9px;
  align-items: center;
  padding: 8px;
}

.symbol-ticket div {
  min-width: 0;
}

.symbol-ticket strong,
.symbol-ticket small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.symbol-ticket strong {
  font-family: "IBM Plex Mono", "Cascadia Code", monospace;
  font-size: 13px;
}

.symbol-ticket small {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}

.symbol-ticket button {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 5px;
  color: var(--muted);
  background: transparent;
}

.symbol-ticket button:hover {
  color: var(--loss);
  background: rgba(199, 71, 64, 0.1);
}

.market-code,
.short-chip {
  padding: 5px 7px;
  border-radius: 5px;
  font-size: 10px;
  font-weight: 900;
}

.market-code.us {
  color: var(--accent-dark);
  background: rgba(21, 155, 141, 0.13);
}

.market-code.hk {
  color: #b45d0c;
  background: rgba(231, 153, 51, 0.15);
}

.short-chip {
  color: #9b4f14;
  background: rgba(224, 108, 24, 0.12);
  white-space: nowrap;
}

.empty-ledger {
  display: flex;
  grid-column: 1 / -1;
  align-items: center;
  justify-content: center;
  gap: 11px;
  color: var(--muted);
}

.empty-ledger strong,
.empty-ledger span {
  display: block;
}

.empty-ledger strong {
  color: var(--ink);
  font-size: 13px;
}

.empty-ledger span {
  margin-top: 2px;
  font-size: 11px;
}

.manual-note {
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  border-left: 3px solid #d9892a;
  color: #7a521f;
  background: rgba(231, 153, 51, 0.1);
  font-size: 11px;
  line-height: 1.55;
}

.universe-actions {
  justify-content: space-between;
  gap: 15px;
  min-height: 62px;
  padding: 11px 18px;
  color: var(--muted);
  font-size: 12px;
}

.universe-actions > button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 15px;
  border: 0;
  border-radius: 6px;
  color: white;
  background: linear-gradient(120deg, var(--accent-dark), var(--accent));
  font-weight: 900;
}

.save-message,
.save-error {
  gap: 6px;
  font-weight: 800;
}

.save-message {
  color: var(--gain);
}

.save-error {
  color: var(--loss);
}

.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1100px) {
  .symbol-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .add-symbol {
    grid-column: span 2;
  }

  .symbol-ledger {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .universe-head,
  .universe-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .mode-switch,
  .symbol-form,
  .symbol-ledger {
    grid-template-columns: 1fr;
  }

  .mode-switch button {
    border-right: 0;
    border-bottom: 1px solid rgba(24, 32, 31, 0.08);
  }

  .add-symbol {
    grid-column: auto;
  }
}
</style>

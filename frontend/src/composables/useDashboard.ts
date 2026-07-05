import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  createBacktest,
  fetchBacktests,
  fetchDashboard,
  fetchLiveSettings,
  streamUrl,
  toggleStrategy as toggleStrategyRequest,
  updateStrategyParams
} from "../api/client";
import type {
  BacktestResult,
  DashboardSnapshot,
  LiveSettingsSnapshot,
  Market,
  ParamValue,
  StrategyConfig,
  WatchSymbol
} from "../api/types";
import { lookupSymbolName } from "../utils/symbolLookup";

/**
 * 有些后端推送来的 watchlist/positions 行 name 字段为空或等于 symbol(旧数据),
 * 在前端用静态映射补一次,这样 UI 里就不会出现「代码 == 名称」的占位显示。
 * 仅当 name 缺失 / 等于 symbol 时覆盖,避免覆盖券商已经正常返回的中文名。
 */
function backfillName<T extends { symbol: string; name: string; market: Market }>(row: T): T {
  const trimmed = (row.name ?? "").trim();
  const needsLookup = trimmed === "" || trimmed === row.symbol;
  if (!needsLookup) return row;
  const name = lookupSymbolName(row.symbol, row.market);
  return name ? { ...row, name } : row;
}

export function useDashboard() {
  const dashboard = ref<DashboardSnapshot | null>(null);
  const liveSettings = ref<LiveSettingsSnapshot | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const streamState = ref<"connecting" | "live" | "offline">("offline");
  const backtest = ref<BacktestResult | null>(null);
  const backtests = ref<BacktestResult[]>([]);
  const backtestRunning = ref(false);
  const backtestProgress = ref(0);
  const backtestProgressLabel = ref("等待回测");
  const backtestError = ref<string | null>(null);
  let socket: WebSocket | null = null;
  let backtestProgressTimer: number | null = null;

  const account = computed(() => dashboard.value?.account ?? null);
  const strategies = computed(() => dashboard.value?.strategies ?? []);
  const risk = computed(() => dashboard.value?.risk ?? []);
  const positions = computed(() => (dashboard.value?.positions ?? []).map(backfillName));
  const watchlist = computed(
    () => (dashboard.value?.watchlist ?? []).map((row) => backfillName(row as WatchSymbol)) as WatchSymbol[]
  );
  const signals = computed(() => dashboard.value?.signals ?? []);
  const orders = computed(() => dashboard.value?.orders ?? []);
  const trades = computed(() => dashboard.value?.trades ?? []);
  const logs = computed(() => dashboard.value?.logs ?? []);
  const chart = computed(() => dashboard.value?.chart ?? []);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      const [dashboardSnapshot, settingsSnapshot] = await Promise.all([
        fetchDashboard(),
        fetchLiveSettings().catch(() => null)
      ]);
      dashboard.value = dashboardSnapshot;
      liveSettings.value = settingsSnapshot;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "加载失败";
    } finally {
      loading.value = false;
    }
  }

  async function loadBacktests() {
    try {
      backtests.value = await fetchBacktests();
      if (!backtest.value) {
        backtest.value = backtests.value[0] ?? null;
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : "回测历史加载失败";
    }
  }

  async function toggleStrategy(strategy: StrategyConfig) {
    const updated = await toggleStrategyRequest(strategy.id, !strategy.enabled);
    patchStrategy(updated);
  }

  async function saveParam(strategy: StrategyConfig, key: string, value: ParamValue) {
    error.value = null;
    try {
      const updated = await updateStrategyParams(strategy.id, { [key]: value });
      patchStrategy(updated);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "参数保存失败";
      strategy.params = { ...strategy.params };
    }
  }

  async function runBacktest(strategyId: string, market: Market) {
    error.value = null;
    backtestError.value = null;
    backtestRunning.value = true;
    backtestProgress.value = 8;
    backtestProgressLabel.value = "提交回测任务";
    startBacktestProgress();
    try {
      const range = backtestDateRange(strategyId);
      const result = await createBacktest({
        strategy_id: strategyId,
        market,
        start_date: range.startDate,
        end_date: range.endDate,
        symbols: backtestSymbols(strategyId, market),
        symbols_mode: "custom",
        initial_capital: 1_000_000,
        symbols_source: backtestSymbolsSource(strategyId, market),
        params_snapshot: strategies.value.find((strategy) => strategy.id === strategyId)?.params ?? {}
      });
      stopBacktestProgress();
      backtestProgress.value = 100;
      backtestProgressLabel.value = "回测完成，CSV 已生成";
      backtest.value = result;
      backtests.value = [
        result,
        ...backtests.value.filter((item) => item.id !== result.id)
      ].slice(0, 20);
      await loadBacktests();
      await load();
    } catch (err) {
      stopBacktestProgress();
      backtestProgress.value = 0;
      backtestProgressLabel.value = "回测失败";
      backtestError.value = err instanceof Error ? err.message : "回测失败";
      error.value = backtestError.value;
    } finally {
      backtestRunning.value = false;
    }
  }

  function startBacktestProgress() {
    stopBacktestProgress();
    backtestProgressTimer = window.setInterval(() => {
      if (backtestProgress.value < 18) {
        backtestProgress.value += 4;
        backtestProgressLabel.value = "提交回测任务";
      } else if (backtestProgress.value < 62) {
        backtestProgress.value += 3;
        backtestProgressLabel.value = "读取行情并计算信号";
      } else if (backtestProgress.value < 88) {
        backtestProgress.value += 2;
        backtestProgressLabel.value = "生成交易明细 CSV";
      }
      backtestProgress.value = Math.min(backtestProgress.value, 88);
    }, 420);
  }

  function stopBacktestProgress() {
    if (backtestProgressTimer !== null) {
      window.clearInterval(backtestProgressTimer);
      backtestProgressTimer = null;
    }
  }

  function backtestDateRange(strategyId: string): { startDate: string; endDate: string } {
    const end = new Date();
    const start = new Date(end);
    if (strategyId === "trend_portfolio") {
      start.setMonth(start.getMonth() - 6);
    } else {
      start.setDate(start.getDate() - 60);
    }
    return {
      startDate: start.toISOString().slice(0, 10),
      endDate: end.toISOString().slice(0, 10)
    };
  }

  function backtestSymbols(strategyId: string, market: Market): string[] {
    const rows = watchlist.value.filter((item) => item.market === market);
    const manualRows = liveSettings.value?.intraday_universe.manual_symbols.filter((item) => item.market === market) ?? [];
    if (strategyId === "trend_portfolio") {
      return [...new Set((manualRows.length > 0 ? manualRows : rows).map((item) => item.symbol))];
    }
    const preferred = rows.filter((item) => item.tags.some((tag) => ["盘前筛选", "手动选股", "等待 15m 收线确认"].includes(tag)));
    return [...new Set((preferred.length > 0 ? preferred : rows).map((item) => item.symbol))];
  }

  function backtestSymbolsSource(strategyId: string, market: Market): string {
    const rows = watchlist.value.filter((item) => item.market === market);
    const manualRows = liveSettings.value?.intraday_universe.manual_symbols.filter((item) => item.market === market) ?? [];
    if (strategyId !== "intraday_macd") {
      return manualRows.length > 0 ? "手动自选候选池" : "自选候选池";
    }
    return rows.some((item) => item.tags.includes("手动选股")) || manualRows.length > 0
      ? "自选候选池（含手动候选）"
      : "自选候选池";
  }

  function selectBacktest(result: BacktestResult) {
    backtest.value = result;
  }

  function connectStream() {
    if (socket) {
      socket.close();
    }
    streamState.value = "connecting";
    socket = new WebSocket(streamUrl());
    socket.onopen = () => {
      streamState.value = "live";
    };
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as { event: string; data: DashboardSnapshot };
      if (payload.event === "snapshot") {
        dashboard.value = payload.data;
      }
    };
    socket.onerror = () => {
      streamState.value = "offline";
    };
    socket.onclose = () => {
      streamState.value = "offline";
    };
  }

  function patchStrategy(updated: StrategyConfig) {
    if (!dashboard.value) {
      return;
    }
    dashboard.value.strategies = dashboard.value.strategies.map((strategy) =>
      strategy.id === updated.id ? updated : strategy
    );
  }

  onMounted(async () => {
    await load();
    await loadBacktests();
    connectStream();
  });

  onBeforeUnmount(() => {
    socket?.close();
    stopBacktestProgress();
  });

  return {
    account,
    backtest,
    backtestError,
    backtestProgress,
    backtestProgressLabel,
    backtestRunning,
    backtests,
    chart,
    dashboard,
    error,
    load,
    loading,
    logs,
    orders,
    positions,
    risk,
    runBacktest,
    saveParam,
    selectBacktest,
    signals,
    strategies,
    streamState,
    toggleStrategy,
    trades,
    watchlist
  };
}

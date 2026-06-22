import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  createBacktest,
  fetchDashboard,
  streamUrl,
  toggleStrategy as toggleStrategyRequest,
  updateStrategyParams
} from "../api/client";
import type {
  BacktestResult,
  DashboardSnapshot,
  Market,
  ParamValue,
  StrategyConfig
} from "../api/types";

export function useDashboard() {
  const dashboard = ref<DashboardSnapshot | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const streamState = ref<"connecting" | "live" | "offline">("offline");
  const backtest = ref<BacktestResult | null>(null);
  let socket: WebSocket | null = null;

  const account = computed(() => dashboard.value?.account ?? null);
  const strategies = computed(() => dashboard.value?.strategies ?? []);
  const risk = computed(() => dashboard.value?.risk ?? []);
  const positions = computed(() => dashboard.value?.positions ?? []);
  const watchlist = computed(() => dashboard.value?.watchlist ?? []);
  const signals = computed(() => dashboard.value?.signals ?? []);
  const orders = computed(() => dashboard.value?.orders ?? []);
  const logs = computed(() => dashboard.value?.logs ?? []);
  const chart = computed(() => dashboard.value?.chart ?? []);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      dashboard.value = await fetchDashboard();
    } catch (err) {
      error.value = err instanceof Error ? err.message : "加载失败";
    } finally {
      loading.value = false;
    }
  }

  async function toggleStrategy(strategy: StrategyConfig) {
    const updated = await toggleStrategyRequest(strategy.id, !strategy.enabled);
    patchStrategy(updated);
  }

  async function saveParam(strategy: StrategyConfig, key: string, value: ParamValue) {
    const updated = await updateStrategyParams(strategy.id, { [key]: value });
    patchStrategy(updated);
  }

  async function runBacktest(strategyId: string, market: Market) {
    backtest.value = await createBacktest({
      strategy_id: strategyId,
      market,
      start_date: "2024-01-01",
      end_date: "2026-06-21",
      symbols: [],
      initial_capital: 1_000_000
    });
    await load();
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
    connectStream();
  });

  onBeforeUnmount(() => {
    socket?.close();
  });

  return {
    account,
    backtest,
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
    signals,
    strategies,
    streamState,
    toggleStrategy,
    watchlist
  };
}


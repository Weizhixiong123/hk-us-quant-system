import type {
  BacktestRequest,
  BacktestResult,
  DashboardSnapshot,
  LiveSettingsSnapshot,
  LiveSettingsUpdate,
  Market,
  ParamValue,
  RuntimeReloadResult,
  StrategyConfig,
  SymbolNameLookup,
  Trade
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      detail = parsed.detail ?? body;
    } catch {
      // 非 JSON 错误响应直接展示原文。
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchDashboard(): Promise<DashboardSnapshot> {
  return request<DashboardSnapshot>("/dashboard");
}

export function fetchLiveSettings(): Promise<LiveSettingsSnapshot> {
  return request<LiveSettingsSnapshot>("/live-settings");
}

export function saveLiveSettings(payload: LiveSettingsUpdate): Promise<LiveSettingsSnapshot> {
  return request<LiveSettingsSnapshot>("/live-settings", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function reloadRuntime(): Promise<RuntimeReloadResult> {
  return request<RuntimeReloadResult>("/runtime/reload", { method: "POST" });
}

export function fetchSymbolName(symbol: string, market: Market): Promise<SymbolNameLookup> {
  const params = new URLSearchParams({ symbol, market });
  return request<SymbolNameLookup>(`/symbols/name?${params}`);
}

export function toggleStrategy(strategyId: string, enabled: boolean): Promise<StrategyConfig> {
  return request<StrategyConfig>(`/strategies/${strategyId}/toggle`, {
    method: "PATCH",
    body: JSON.stringify({ enabled })
  });
}

export function updateStrategyParams(
  strategyId: string,
  params: Record<string, ParamValue>
): Promise<StrategyConfig> {
  return request<StrategyConfig>(`/strategies/${strategyId}/params`, {
    method: "PUT",
    body: JSON.stringify({ params })
  });
}

export function fetchBacktests(limit = 20): Promise<BacktestResult[]> {
  return request<BacktestResult[]>(`/backtests?limit=${limit}`);
}

export function fetchTradeHistory(limit = 200): Promise<Trade[]> {
  return request<Trade[]>(`/trades/history?limit=${limit}`);
}

export function createBacktest(payload: BacktestRequest): Promise<BacktestResult> {
  return request<BacktestResult>("/backtests", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function backtestTradesCsvUrl(backtestId: string): string {
  return `${API_BASE}/backtests/${encodeURIComponent(backtestId)}/trades.csv`;
}

export function streamUrl(): string {
  if (import.meta.env.VITE_WS_BASE) {
    return `${import.meta.env.VITE_WS_BASE}/ws/stream`;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${API_BASE}/ws/stream`;
}


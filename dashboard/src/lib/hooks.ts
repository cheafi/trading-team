import useSWR from "swr";

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export interface Agent {
  id: string;
  name: string;
  emoji: string;
  status: "idle" | "running" | "error";
  lastRun: string | null;
  findingsCount: number;
  latestFinding: Finding | null;
}

export interface Finding {
  timestamp: string;
  agent: string;
  type: string;
  data: Record<string, unknown>;
  summary: string;
}

export interface StrategyPerf {
  pair: string;
  profit: number;
  count: number;
}

export interface ProfitData {
  profit_all_coin: number;
  profit_all_percent: number;
  profit_all_ratio: number;
  profit_closed_coin: number;
  profit_closed_percent: number;
  trade_count: number;
  closed_trade_count: number;
  winning_trades: number;
  losing_trades: number;
  max_drawdown: number;
  max_drawdown_abs: number;
  profit_factor: number;
  winrate: number;
  expectancy: number;
  sharpe: number;
  sortino: number;
}

export function useAgents() {
  return useSWR<Agent[]>("/api/agents", fetcher, {
    refreshInterval: 5000,
    fallbackData: [],
  });
}

export function useFindings(limit = 30) {
  return useSWR<Finding[]>(`/api/findings?limit=${limit}`, fetcher, {
    refreshInterval: 10000,
    fallbackData: [],
  });
}

export function useStrategies() {
  return useSWR<{ performance: StrategyPerf[]; profit: ProfitData }>(
    "/api/strategies",
    fetcher,
    {
      refreshInterval: 15000,
      fallbackData: { performance: [], profit: {} as ProfitData },
    }
  );
}

export function useProfit() {
  return useSWR<ProfitData>("/api/ft/profit", fetcher, {
    refreshInterval: 10000,
  });
}

export function useBalance() {
  return useSWR("/api/ft/balance", fetcher, {
    refreshInterval: 30000,
  });
}

export function useTrades() {
  return useSWR("/api/ft/status", fetcher, {
    refreshInterval: 5000,
    fallbackData: [],
  });
}

export interface MLState {
  regime: string;
  strategy: string;
  winRate: number;
  maxDD: number;
  improvementTrend: string;
  params: Record<string, {
    c: number;
    e: number;
    roi_0: number;
    sl: number;
    strategy: string;
    source_score: number;
    win_rate: number;
    sharpe: number;
  }> | null;
  lastTrained: string | null;
  updatedAt: string;
}

export function useMLState() {
  return useSWR<MLState>("/api/ml/state", fetcher, {
    refreshInterval: 10000,
  });
}

export interface PairPerf {
  pair: string;
  profit: number;
  profit_abs: number;
  count: number;
}

export function usePerformance() {
  return useSWR<PairPerf[]>("/api/ft/performance", fetcher, {
    refreshInterval: 15000,
    fallbackData: [],
  });
}

export interface TrainingEntry {
  timestamp: string;
  trade_count: number;
  strategy_scores: Record<string, {
    total_profit: number;
    win_rate: number;
    sharpe: number;
    profit_factor: number;
    score: number;
  }>;
  best_params: Record<string, unknown>;
}

export function useMLHistory() {
  return useSWR<TrainingEntry[]>("/api/ml/history", fetcher, {
    refreshInterval: 60000,
    fallbackData: [],
  });
}

// ─── ML Job Control ─────────────────────────────────────
export interface MLJob {
  id: string;
  status: "running" | "finished" | "failed";
  startedAt: string;
  finishedAt?: string;
  exitCode?: number;
  source: string;
  pid?: number;
}

export function useMLJobs(limit = 10) {
  return useSWR<MLJob[]>(`/api/ml/jobs?limit=${limit}`, fetcher, {
    refreshInterval: 5000,
    fallbackData: [],
  });
}

export function useMLJobLogs(jobId: string | null, limit = 200) {
  return useSWR<string[]>(
    jobId ? `/api/ml/jobs/${jobId}/logs?limit=${limit}` : null,
    fetcher,
    { refreshInterval: 2000, fallbackData: [] }
  );
}

export async function triggerMLTrain(): Promise<{ status: string; jobId?: string; error?: string }> {
  const res = await fetch("/api/ml/train", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return res.json();
}

// ─── Diagnostics ─────────────────────────────────────────

export interface RejectionEntry {
  timestamp: string;
  pair: string;
  side: string;
  reason: string;
  regime: string;
  details?: Record<string, unknown>;
}

export function useRejections(limit = 50) {
  return useSWR<RejectionEntry[]>(
    `/api/diagnostics/rejections?limit=${limit}`,
    fetcher,
    {
      refreshInterval: 30000,
      fallbackData: [],
    }
  );
}

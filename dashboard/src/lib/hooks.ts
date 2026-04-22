import useSWR from "swr";

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

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

// ─── Funding Rates ──────────────────────────────────────
export interface FundingRate {
  symbol: string;
  pair: string;
  fundingRate: number;
  markPrice: number;
  indexPrice: number;
  nextFundingTime: number;
  time: number;
}

export function useFunding() {
  return useSWR<FundingRate[]>("/api/funding", fetcher, {
    refreshInterval: 60000,
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
  regime: number | string | null;
  direction_score: number | null;
  details?: Record<string, unknown>;
  risk?: {
    consecutive_losses: number;
    daily_pnl: number;
    daily_trades: number;
  };
  features?: Record<string, number>;
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

// ─── Decision Journal v4 ────────────────────────────────

export interface DecisionEntry {
  time: string;
  pair: string;
  side: string;
  decision: "accept" | "reject";
  reason: string;
  rate: number | null;
  edge_score: number | null;
  quality_threshold: number | null;
  regime: number | string | null;
  direction_score: number | null;
  risk?: {
    consecutive_losses: number;
    daily_pnl: number;
    daily_trades: number;
  };
  model_ts?: number;
  features?: Record<string, number>;
}

export interface DecisionJournalResponse {
  total: number;
  totalAccept: number;
  totalReject: number;
  acceptRate: number;
  entries: DecisionEntry[];
}

export function useDecisionJournal(filters?: {
  pair?: string;
  decision?: string;
  side?: string;
  reason?: string;
  from?: string;
  to?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (filters?.pair) params.set("pair", filters.pair);
  if (filters?.decision) params.set("decision", filters.decision);
  if (filters?.side) params.set("side", filters.side);
  if (filters?.reason) params.set("reason", filters.reason);
  if (filters?.from) params.set("from", filters.from);
  if (filters?.to) params.set("to", filters.to);
  if (filters?.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return useSWR<DecisionJournalResponse>(
    `/api/diagnostics/decisions${qs ? `?${qs}` : ""}`,
    fetcher,
    {
      refreshInterval: 30000,
      fallbackData: { total: 0, totalAccept: 0, totalReject: 0, acceptRate: 0, entries: [] },
    }
  );
}

// ─── Risk Cockpit ────────────────────────────────────────

export interface RiskCockpitData {
  open_trades: number;
  gross_exposure: number;
  net_exposure: number;
  pair_exposure: Record<string, number>;
  max_concentration: number;
  worst_case_loss: number;
  max_drawdown: number;
  max_drawdown_abs: number;
  leverage: { max: number; avg: number };
  dd_guard: {
    daily_pnl: number;
    daily_pnl_pct: number;
    daily_trades: number;
    daily_limit: number;
    daily_breached: boolean;
    weekly_pnl: number;
    weekly_pnl_pct: number;
    weekly_trades: number;
    weekly_limit: number;
    weekly_breached: boolean;
  };
  model_drift: {
    status: string;
    drifted: boolean;
    active_version?: string;
    active_since?: string;
    params_hash?: string;
    feature_hash?: string;
    data_hash?: string;
    training_window?: { start: string; end: string; n_trades: number };
    validation_window?: { start: string; end: string; n_trades: number };
  };
}

export function useRiskCockpit() {
  return useSWR<RiskCockpitData>("/api/risk/cockpit", fetcher, {
    refreshInterval: 10000,
  });
}

// ─── Model Registry ──────────────────────────────────────

export interface ModelVersion {
  version_id: string;
  timestamp: string;
  params_hash: string;
  artifacts: string[];
  oos_metrics: {
    total_trades?: number;
    avg_win_rate?: number;
    strategies_scored?: number;
  };
  drift: Record<string, unknown> | null;
  total_trades?: number;
  trigger?: string;
}

export interface RegistryData {
  active: string | null;
  versions: ModelVersion[];
}

export function useModelRegistry() {
  return useSWR<RegistryData>("/api/ml/registry", fetcher, {
    refreshInterval: 30000,
    fallbackData: { active: null, versions: [] },
  });
}

// ─── Trade Replay ────────────────────────────────────────

export interface ReplayEntry {
  event: "entry" | "exit";
  time: string;
  pair: string;
  side: string;
  entry_tag?: string;
  exit_reason?: string;
  profit_ratio?: number;
  rate?: number;
  entry_rate?: number;
  exit_rate?: number;
  duration_min?: number;
  regime?: number;
  features?: Record<string, number>;
  features_at_exit?: Record<string, number>;
  risk?: {
    consecutive_losses: number;
    daily_pnl: number;
    daily_trades?: number;
  };
}

export function useTradeReplay(limit = 50) {
  return useSWR<ReplayEntry[]>(
    `/api/diagnostics/replay?limit=${limit}`,
    fetcher,
    {
      refreshInterval: 15000,
      fallbackData: [],
    }
  );
}

// ─── Shadow Model Comparison ─────────────────────────────

export interface ShadowComparison {
  total: number;
  agrees: number;
  disagrees: number;
  agreement_rate: number | null;
  recent: Array<ReplayEntry & {
    shadow?: {
      quality: number;
      threshold: number;
      would_allow: boolean;
    };
  }>;
}

export function useShadowComparison() {
  return useSWR<ShadowComparison>("/api/ml/shadow", fetcher, {
    refreshInterval: 30000,
    fallbackData: {
      total: 0,
      agrees: 0,
      disagrees: 0,
      agreement_rate: null,
      recent: [],
    },
  });
}

// ─── Benchmark Centre ────────────────────────────────────

export interface BenchmarkData {
  strategy_return_pct: number;
  trading_days: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  max_drawdown_pct: string;
  profit_factor: number;
  win_rate: number;
  expectancy: number;
  trade_count: number;
  closed_trades: number;
  benchmarks: Record<string, { return_pct: number; label: string }>;
  pair_breakdown: Record<string, { trades: number; profit_pct: number }>;
}

export function useBenchmark() {
  return useSWR<BenchmarkData>("/api/benchmark", fetcher, {
    refreshInterval: 30000,
  });
}

// ─── Kill Switch ─────────────────────────────────────────

export interface KillSwitchData {
  active: boolean;
  activated_at?: string;
  reason?: string;
  source?: string;
}

export function useKillSwitch() {
  return useSWR<KillSwitchData>("/api/kill-switch", fetcher, {
    refreshInterval: 5000,
    fallbackData: { active: false },
  });
}

export async function toggleKillSwitch(active: boolean, reason?: string): Promise<KillSwitchData> {
  const res = await fetch("/api/kill-switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active, reason }),
  });
  if (!res.ok) {
    throw new Error(`Kill-switch toggle failed: HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Backtest Control ────────────────────────────────────

export interface BacktestResult {
  strategy: string;
  timerange: string;
  timeframe?: string;
  profit: number;
  winRate: number;
  maxDrawdown: number;
  totalTrades: number;
  sharpe: number;
  timestamp: string;
  error?: string;
}

export function useBacktestResults() {
  return useSWR<BacktestResult[]>("/api/backtest/results", fetcher, {
    refreshInterval: 5000,
    fallbackData: [],
  });
}

export async function triggerBacktest(params: {
  strategy?: string;
  timerange?: string;
  timeframe?: string;
}): Promise<{ status: string; strategies?: string[]; timerange?: string; timeframe?: string; error?: string }> {
  const res = await fetch("/api/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      return JSON.parse(text);
    } catch {
      return { status: "error", error: `HTTP ${res.status}: ${text.slice(0, 100)}` };
    }
  }
  return res.json();
}

// ─── Trade History (closed trades) ───────────────────────

export interface ClosedTrade {
  trade_id: number;
  pair: string;
  is_short: boolean;
  open_date: string;
  close_date: string;
  profit_pct: number;
  profit_abs: number;
  open_rate: number;
  close_rate: number;
  stake_amount: number;
  exit_reason: string;
  enter_tag: string;
  timeframe: string;
  min_rate: number;
  max_rate: number;
  close_profit: number;
}

export function useTradeHistory(limit = 50) {
  return useSWR<{ trades: ClosedTrade[]; trades_count: number }>(
    `/api/ft/trades?limit=${limit}`,
    fetcher,
    {
      refreshInterval: 15000,
    }
  );
}

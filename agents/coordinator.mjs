/**
 * Agent Coordinator — Orchestrates the 7-agent trading team
 *
 * Architecture: modular split (Phase 2)
 *   ft-client.mjs    — Freqtrade API wrapper + self-test
 *   job-manager.mjs  — ML training, backtest, download jobs
 *   discord-bot.mjs  — Discord integration
 *   coordinator.mjs  — Agent definitions, task runners, cron, HTTP routes
 */
import { createServer } from "node:http";
import Redis from "ioredis";
import { CronJob } from "cron";
import pino from "pino";
import discord from "./discord-bot.mjs";
import { ftApi, selfTestFT, FT_PASS, FREQTRADE_API } from "./ft-client.mjs";
import {
  startTrainingJob,
  getDefaultTimerange,
  downloadData,
  runBacktests,
  getBacktestResults,
} from "./job-manager.mjs";

const log = pino({
  level: process.env.LOG_LEVEL || "info",
  transport:
    process.env.NODE_ENV !== "production"
      ? { target: "pino-pretty" }
      : undefined,
});

// ─── Config ────────────────────────────────────────────────────
const REDIS_URL = process.env.REDIS_URL || "redis://redis:6379";
const PORT = parseInt(process.env.AGENT_PORT || "3001", 10);
const TZ = process.env.TZ || "Asia/Hong_Kong";

// ─── Redis ─────────────────────────────────────────────────────
const redis = new Redis(REDIS_URL, {
  retryStrategy: (times) => Math.min(times * 200, 5000),
  maxRetriesPerRequest: 3,
});

redis.on("connect", () => log.info("Redis connected"));
redis.on("error", (err) => log.error({ err }, "Redis error"));

// ─── Agent Definitions ─────────────────────────────────────────
const agents = [
  {
    id: "quant-researcher",
    name: "Quant Researcher",
    emoji: "🔬",
    schedule: "*/15 * * * *", // every 15 min
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "backtester",
    name: "Backtester",
    emoji: "📊",
    schedule: "0 */2 * * *", // every 2 hours
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "risk-manager",
    name: "Risk Manager",
    emoji: "🛡️",
    schedule: "*/5 * * * *", // every 5 min
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "signal-engineer",
    name: "Signal Engineer",
    emoji: "📡",
    schedule: "*/5 * * * *", // every 5 min
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "market-analyst",
    name: "Market Analyst",
    emoji: "🌍",
    schedule: "*/10 * * * *", // every 10 min
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "security-auditor",
    name: "Security Auditor",
    emoji: "🔒",
    schedule: "0 */6 * * *", // every 6 hours
    status: "idle",
    lastRun: null,
    findings: [],
  },
  {
    id: "ml-optimizer",
    name: "ML State Monitor",
    emoji: "🧠",
    schedule: "0 */2 * * *", // every 2 hours — refresh ML state (does NOT retrain)
    status: "idle",
    lastRun: null,
    findings: [],
  },
];

// ─── Agent Task Runners ────────────────────────────────────────

async function runQuantResearcher(agent) {
  log.info(`[${agent.id}] Analyzing market structure...`);

  const profit = await ftApi("/profit");
  const performance = await ftApi("/performance");
  const status = await ftApi("/status");

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "analysis",
    data: {
      totalProfit: profit?.profit_all_coin || 0,
      profitPercent: profit?.profit_all_percent || 0,
      tradeCount: profit?.trade_count || 0,
      topStrategies:
        performance?.slice(0, 5).map((p) => ({
          pair: p.pair,
          profit: p.profit,
          count: p.count,
        })) || [],
      openTrades: status?.length || 0,
    },
    summary: `P&L: ${profit?.profit_all_coin?.toFixed(2) || "N/A"} USDT | Open: ${status?.length || 0} trades`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

async function runBacktester(agent) {
  log.info(`[${agent.id}] Checking data freshness + backtest metrics...`);

  const fs = await import("node:fs/promises");
  const strategies = [
    "A52Strategy",
    "OPTStrategy",
    "A51Strategy",
    "A31Strategy",
  ];

  // ── Data freshness check ──────────────────────────
  // If best_params.json is older than 7 days, trigger
  // download → backtest → retrain cycle automatically.
  let paramsAgeDays = null;
  let refreshTriggered = false;
  const paramsPath = "/freqtrade/user_data/ml_models/best_params.json";

  try {
    const stat = await fs.stat(paramsPath);
    paramsAgeDays = (Date.now() - stat.mtimeMs) / 86_400_000;
  } catch {
    paramsAgeDays = null; // file doesn't exist
  }

  if (paramsAgeDays === null || paramsAgeDays > 7) {
    log.warn(
      `[${agent.id}] ML params are ${paramsAgeDays === null ? "missing" : `${paramsAgeDays.toFixed(1)} days old`} — triggering auto-refresh`,
    );
    try {
      // Step 1: Download fresh data (last 6 months)
      const tr = getDefaultTimerange();
      const pairs = [
        "ETH/USDT:USDT",
        "BTC/USDT:USDT",
        "SOL/USDT:USDT",
        "BNB/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
      ];
      const timeframes = ["5m", "15m", "1h"];
      log.info(`[${agent.id}] Downloading data for ${tr}...`);
      await downloadData(pairs, timeframes, tr, discord);

      // Step 2: Run backtests for all strategies
      log.info(`[${agent.id}] Running backtests...`);
      await runBacktests(strategies, tr, redis, discord);

      // Step 3: Trigger ML retrain
      log.info(`[${agent.id}] Triggering ML retrain...`);
      await startTrainingJob(redis, { timerange: tr });

      refreshTriggered = true;
      log.info(`[${agent.id}] Auto-refresh complete`);
    } catch (err) {
      log.error(
        `[${agent.id}] Auto-refresh failed: ${err.message}`,
      );
    }
  }

  // ── Pull pair performance from the running bot ─────
  const performance = await ftApi("/performance");

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "backtest-review",
    data: {
      pairPerformance:
        performance?.slice(0, 10)?.map((p) => ({
          pair: p.pair,
          profit: p.profit,
          count: p.count,
        })) || [],
      monitoredStrategies: strategies,
      paramsAgeDays: paramsAgeDays !== null ? +paramsAgeDays.toFixed(1) : null,
      refreshTriggered,
    },
    summary: refreshTriggered
      ? `Auto-refresh triggered (params ${paramsAgeDays === null ? "missing" : paramsAgeDays.toFixed(0) + "d old"}) | ${performance?.length || 0} pairs`
      : `Params ${paramsAgeDays !== null ? paramsAgeDays.toFixed(0) + "d old" : "missing"} | ${strategies.length} strategies | ${performance?.length || 0} pairs`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

async function runRiskManager(agent) {
  log.info(`[${agent.id}] Evaluating risk exposure...`);

  const balance = await ftApi("/balance");
  const status = await ftApi("/status");
  const profit = await ftApi("/profit");

  const totalValue = balance?.total || 0;
  const openTrades = status?.length || 0;
  const ddRaw = profit?.max_drawdown ?? 0;
  const drawdownPct = ddRaw > 1 ? ddRaw : ddRaw * 100;

  const alerts = [];
  if (drawdownPct > 15)
    alerts.push(`⚠️ DD ${drawdownPct.toFixed(1)}% > 15% threshold`);
  if (openTrades > 4) alerts.push(`⚠️ ${openTrades} open positions (max: 4)`);

  const riskLevel =
    drawdownPct > 20
      ? "CRITICAL"
      : drawdownPct > 15
        ? "HIGH"
        : drawdownPct > 10
          ? "MEDIUM"
          : "LOW";

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "risk-assessment",
    data: {
      totalValue,
      openTrades,
      drawdownPct,
      riskLevel,
      alerts,
    },
    summary: `Risk: ${riskLevel} | DD: ${drawdownPct?.toFixed(1) || 0}% | Open: ${openTrades}`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);

  // Publish risk alerts to Redis for real-time dashboard
  if (alerts.length > 0) {
    await redis.publish(
      "trading:alerts",
      JSON.stringify({ alerts, riskLevel }),
    );
  }

  // Send risk alert to Discord if HIGH or CRITICAL
  if (riskLevel === "HIGH" || riskLevel === "CRITICAL") {
    discord
      .sendRiskAlert({ riskLevel, drawdownPct: drawdownPct, alerts })
      .catch(() => {});
  }

  return finding;
}

async function runSignalEngineer(agent) {
  log.info(`[${agent.id}] Processing signals...`);

  const status = await ftApi("/status");
  const whitelist = await ftApi("/whitelist");

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "signal-report",
    data: {
      activeSignals:
        status?.map((t) => ({
          pair: t.pair,
          direction: t.is_short ? "SHORT" : "LONG",
          profit: t.profit_pct,
          duration: t.trade_duration,
          strategy: t.strategy,
          entryTag: t.enter_tag,
        })) || [],
      watchlist: whitelist?.whitelist || [],
    },
    summary: `${status?.length || 0} active signals | Watching ${whitelist?.whitelist?.length || 0} pairs`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

async function runMarketAnalyst(agent) {
  log.info(`[${agent.id}] Scanning portfolio posture...`);

  const status = await ftApi("/status");

  // Portfolio posture: derived from open trade directions.
  // This agent does NOT perform independent market analysis
  // (that would require candle data the coordinator doesn't fetch).
  const longTrades = status?.filter((t) => !t.is_short)?.length || 0;
  const shortTrades = status?.filter((t) => t.is_short)?.length || 0;
  const pairs = [...new Set(status?.map((t) => t.pair) || [])];

  const posture =
    longTrades > shortTrades
      ? "NET_LONG"
      : shortTrades > longTrades
        ? "NET_SHORT"
        : "FLAT";

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "portfolio-posture",
    data: {
      pairs,
      posture,
      longTrades,
      shortTrades,
      timestamp: Date.now(),
    },
    summary: `Posture: ${posture} (L:${longTrades} S:${shortTrades}) | ${pairs.length} pair(s)`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

async function runSecurityAuditor(agent) {
  log.info(`[${agent.id}] Running security checks...`);

  const version = await ftApi("/version");
  const health = await ftApi("/health");
  const locks = await ftApi("/locks");

  const issues = [];
  if (!health) issues.push("Freqtrade health check failed");
  if (locks?.lock_count > 0)
    issues.push(`${locks.lock_count} pair locks active`);

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "security-audit",
    data: {
      freqtradeVersion: version?.version || "unknown",
      apiHealth: !!health,
      pairLocks: locks?.lock_count || 0,
      issues,
    },
    summary: `FT ${version?.version || "?"} | Issues: ${issues.length}`,
  };

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

async function runMLStateRefresh(agent) {
  log.info(`[${agent.id}] Refreshing ML state (read-only, no training)...`);

  // 1. Get current performance to evaluate if retraining is needed
  const profit = await ftApi("/profit");
  const performance = await ftApi("/performance");

  const winRate =
    profit?.trade_count > 0
      ? (profit?.winning_trades || 0) / profit.trade_count
      : 0;
  const maxDDRaw = profit?.max_drawdown ?? 0;
  const maxDD = maxDDRaw > 1 ? maxDDRaw : maxDDRaw * 100;
  const totalProfit = profit?.profit_all_coin || 0;

  // 2. Read current ML model params (if they exist)
  let currentParams = null;
  try {
    const fs = await import("node:fs/promises");
    const paramsPath = "/freqtrade/user_data/ml_models/best_params.json";
    const raw = await fs.readFile(paramsPath, "utf8");
    currentParams = JSON.parse(raw);
  } catch {
    currentParams = null;
  }

  // 3. Read training log for improvement tracking
  let trainingLog = [];
  try {
    const fs = await import("node:fs/promises");
    const logPath = "/freqtrade/user_data/ml_models/training_log.json";
    const raw = await fs.readFile(logPath, "utf8");
    trainingLog = JSON.parse(raw);
  } catch {
    trainingLog = [];
  }

  // 4. Calculate improvement trend
  let improvementTrend = "stable";
  if (trainingLog.length >= 2) {
    const recent = trainingLog.slice(-5);
    const scores = recent.map((entry) => {
      const strats = Object.values(entry.strategy_scores || {});
      return (
        strats.reduce((sum, s) => sum + (s.score || 0), 0) /
        (strats.length || 1)
      );
    });
    const firstHalf = scores.slice(0, Math.floor(scores.length / 2));
    const secondHalf = scores.slice(Math.floor(scores.length / 2));
    const avgFirst =
      firstHalf.reduce((a, b) => a + b, 0) / (firstHalf.length || 1);
    const avgSecond =
      secondHalf.reduce((a, b) => a + b, 0) / (secondHalf.length || 1);

    if (avgSecond > avgFirst * 1.05) improvementTrend = "improving";
    else if (avgSecond < avgFirst * 0.95) improvementTrend = "degrading";
  }

  // 5. Determine best-performing regime from model params
  // Note: this is the regime with highest optimizer score,
  // NOT the current live candle regime (which requires indicator data)
  let activeRegime = "unknown";
  let activeStrategy = "A52";
  if (currentParams) {
    const regimeNames = {
      0: "TRENDING_UP",
      1: "TRENDING_DOWN",
      2: "RANGING",
      3: "VOLATILE",
    };
    let bestScore = -Infinity;
    for (const [rid, params] of Object.entries(currentParams)) {
      const score = parseFloat(params.source_score || 0);
      if (score > bestScore) {
        bestScore = score;
        activeRegime = regimeNames[rid] || `Regime-${rid}`;
        activeStrategy = params.strategy || "A52";
      }
    }
  }

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "ml-state-refresh",
    data: {
      winRate: parseFloat(winRate.toFixed(4)),
      maxDD: parseFloat(maxDD.toFixed(2)),
      totalProfit: parseFloat((totalProfit || 0).toFixed(2)),
      currentParams,
      activeRegime,
      activeStrategy,
      improvementTrend,
      trainingRuns: trainingLog.length,
      strategies:
        performance?.slice(0, 5).map((p) => ({
          pair: p.pair,
          profit: p.profit,
          count: p.count,
        })) || [],
    },
    summary: `ML: regime=${activeRegime} strategy=${activeStrategy} WR=${(winRate * 100).toFixed(1)}% trend=${improvementTrend}`,
  };

  // 6. Publish ML state to Redis for dashboard
  await redis.set(
    "trading:ml:state",
    JSON.stringify({
      regime: activeRegime,
      strategy: activeStrategy,
      winRate,
      maxDD,
      improvementTrend,
      params: currentParams,
      lastTrained:
        trainingLog.length > 0
          ? trainingLog[trainingLog.length - 1].timestamp
          : null,
      updatedAt: new Date().toISOString(),
    }),
  );

  // 7. Notify Discord about ML state (periodic refresh, NOT training)
  discord
    .sendMLStateUpdate({
      summary: finding.summary,
      regime: activeRegime,
      strategy: activeStrategy,
      trend: improvementTrend,
    })
    .catch(() => {});

  agent.findings.unshift(finding);
  agent.findings = agent.findings.slice(0, 50);
  return finding;
}

// Spawn a background ML training job via job-manager module.
// Re-exported for backward compatibility with HTTP routes.
async function _startTrainingJob(source = "api") {
  return startTrainingJob(redis, {
    source,
    agents,
    runMLStateRefresh,
    discord,
  });
}

const taskRunners = {
  "quant-researcher": runQuantResearcher,
  backtester: runBacktester,
  "risk-manager": runRiskManager,
  "signal-engineer": runSignalEngineer,
  "market-analyst": runMarketAnalyst,
  "security-auditor": runSecurityAuditor,
  "ml-optimizer": runMLStateRefresh,
};

// ─── Execute Agent Task ────────────────────────────────────────
async function executeAgent(agent) {
  const runner = taskRunners[agent.id];
  if (!runner) return;

  agent.status = "running";
  const startTime = Date.now();

  try {
    const finding = await runner(agent);

    agent.status = "idle";
    agent.lastRun = new Date().toISOString();

    // Store state in Redis for dashboard
    await redis.hset(
      "trading:agents",
      agent.id,
      JSON.stringify({
        ...agent,
        lastDuration: Date.now() - startTime,
      }),
    );

    // Store latest finding
    if (finding) {
      await redis.lpush(
        `trading:findings:${agent.id}`,
        JSON.stringify(finding),
      );
      await redis.ltrim(`trading:findings:${agent.id}`, 0, 99);

      // Also push to global findings stream
      await redis.lpush("trading:findings:all", JSON.stringify(finding));
      await redis.ltrim("trading:findings:all", 0, 499);

      // Send important findings to Discord
      const importantTypes = [
        "risk-assessment",
        "signal-report",
        "security-audit",
        "ml-optimization",
      ];
      if (importantTypes.includes(finding.type)) {
        discord.sendFinding({ ...finding, emoji: agent.emoji }).catch(() => {});
      }
    }

    log.info(
      { agent: agent.id, duration: Date.now() - startTime },
      "Agent completed",
    );
  } catch (err) {
    agent.status = "error";
    log.error({ err, agent: agent.id }, "Agent execution failed");

    await redis.hset(
      "trading:agents",
      agent.id,
      JSON.stringify({
        ...agent,
        error: err.message,
      }),
    );
  }
}

// ─── Cron Scheduling ───────────────────────────────────────────
const jobs = [];

function startScheduler() {
  for (const agent of agents) {
    const job = new CronJob(
      agent.schedule,
      () => executeAgent(agent),
      null,
      true,
      TZ,
    );
    jobs.push(job);
    log.info({ agent: agent.id, schedule: agent.schedule }, "Scheduled agent");
  }
}

// ─── Auth helpers ──────────────────────────────────────────────
const API_KEY = process.env.ML_TRAIN_API_KEY || "";
const ALLOW_OPEN_AUTH = process.env.ALLOW_OPEN_AUTH === "true";
const ALLOWED_ORIGINS = (
  process.env.CORS_ORIGINS || "http://localhost:3000,http://dashboard:3000"
)
  .split(",")
  .map((s) => s.trim());

function checkAuth(req) {
  if (!API_KEY) {
    if (ALLOW_OPEN_AUTH) return true;
    log.warn("Mutating request blocked: ML_TRAIN_API_KEY not set and ALLOW_OPEN_AUTH !== 'true'");
    return false;
  }
  const provided = req.headers["x-api-key"];
  return provided === API_KEY;
}

// ─── HTTP API (for dashboard) ──────────────────────────────────
const server = createServer(async (req, res) => {
  const origin = req.headers.origin || "";
  const allowedOrigin = ALLOWED_ORIGINS.includes(origin)
    ? origin
    : ALLOWED_ORIGINS[0];
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Access-Control-Allow-Origin", allowedOrigin);
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-API-Key");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  try {
    // Health check
    if (url.pathname === "/health") {
      res.writeHead(200);
      res.end(JSON.stringify({ ok: true, agents: agents.length }));
      return;
    }

    // Get all agents status
    if (url.pathname === "/api/agents") {
      res.writeHead(200);
      res.end(
        JSON.stringify(
          agents.map((a) => ({
            id: a.id,
            name: a.name,
            emoji: a.emoji,
            status: a.status,
            lastRun: a.lastRun,
            findingsCount: a.findings.length,
            latestFinding: a.findings[0] || null,
          })),
        ),
      );
      return;
    }

    // Get specific agent findings
    if (
      url.pathname.startsWith("/api/agents/") &&
      url.pathname.endsWith("/findings")
    ) {
      const agentId = url.pathname.split("/")[3];
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) {
        res.writeHead(404);
        res.end(JSON.stringify({ error: "Agent not found" }));
        return;
      }
      const limit = parseInt(url.searchParams.get("limit") || "20", 10);
      res.writeHead(200);
      res.end(JSON.stringify(agent.findings.slice(0, limit)));
      return;
    }

    // Get all findings (global stream)
    if (url.pathname === "/api/findings") {
      const limit = parseInt(url.searchParams.get("limit") || "50", 10);
      const findings = await redis.lrange("trading:findings:all", 0, limit - 1);
      res.writeHead(200);
      res.end(JSON.stringify(findings.map((f) => JSON.parse(f))));
      return;
    }

    // Get strategy rankings
    if (url.pathname === "/api/strategies") {
      const performance = await ftApi("/performance");
      const profit = await ftApi("/profit");
      res.writeHead(200);
      res.end(
        JSON.stringify({
          performance: performance || [],
          profit: profit || {},
        }),
      );
      return;
    }

    // Trigger agent manually (requires API key)
    if (url.pathname === "/api/run" && req.method === "POST") {
      if (!checkAuth(req)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: "Forbidden: invalid API key" }));
        return;
      }
      let body = "";
      for await (const chunk of req) body += chunk;
      const { agentId } = JSON.parse(body);
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) {
        res.writeHead(404);
        res.end(JSON.stringify({ error: "Agent not found" }));
        return;
      }
      executeAgent(agent); // fire and forget
      res.writeHead(202);
      res.end(JSON.stringify({ status: "triggered", agent: agentId }));
      return;
    }

    // Freqtrade proxy
    if (url.pathname.startsWith("/api/ft/")) {
      const ftPath = url.pathname.replace("/api/ft", "");
      const data = await ftApi(ftPath);
      res.writeHead(data ? 200 : 502);
      res.end(JSON.stringify(data || { error: "Freqtrade unavailable" }));
      return;
    }

    // ML state endpoint
    if (url.pathname === "/api/ml/state") {
      const mlState = await redis.get("trading:ml:state");
      res.writeHead(200);
      res.end(
        mlState ||
          JSON.stringify({ regime: "unknown", strategy: "A52", params: null }),
      );
      return;
    }

    // ML training log
    if (url.pathname === "/api/ml/history") {
      try {
        const fs = await import("node:fs/promises");
        const logPath = "/freqtrade/user_data/ml_models/training_log.json";
        const raw = await fs.readFile(logPath, "utf8");
        res.writeHead(200);
        res.end(raw);
      } catch {
        res.writeHead(200);
        res.end(JSON.stringify([]));
      }
      return;
    }

    // List recent ML jobs
    if (url.pathname === "/api/ml/jobs") {
      const limit = parseInt(url.searchParams.get("limit") || "20", 10);
      try {
        const raw = await redis.lrange(
          "trading:jobs:ml_training:results",
          0,
          limit - 1,
        );
        const jobs = raw.map((r) => JSON.parse(r));
        res.writeHead(200);
        res.end(JSON.stringify(jobs));
      } catch (err) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: err.message }));
      }
      return;
    }

    // Get logs for a specific job
    if (
      url.pathname.startsWith("/api/ml/jobs/") &&
      url.pathname.endsWith("/logs")
    ) {
      // path: /api/ml/jobs/:id/logs  →  ["", "api", "ml", "jobs", ID, "logs"]
      const parts = url.pathname.split("/");
      const jobId = parts[4];
      if (!jobId) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: "missing job id" }));
        return;
      }
      const limit = parseInt(url.searchParams.get("limit") || "500", 10);
      try {
        const key = `trading:jobs:ml_training:logs:${jobId}`;
        const raw = await redis.lrange(key, 0, limit - 1);
        res.writeHead(200);
        res.end(JSON.stringify(raw));
      } catch (err) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: err.message }));
      }
      return;
    }

    // Trigger ML training manually (requires API key)
    if (url.pathname === "/api/ml/train" && req.method === "POST") {
      if (!checkAuth(req)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: "Forbidden: invalid API key" }));
        return;
      }

      // Rate-limit cooldown: minimum 5 minutes between training starts
      const cdKey = "trading:job:ml_training_cooldown";
      const cdVal = await redis.get(cdKey);
      if (cdVal) {
        res.writeHead(429);
        res.end(
          JSON.stringify({
            error: "Training cooldown active. Try again later.",
            cooldownUntil: cdVal,
          }),
        );
        return;
      }

      try {
        const job = await _startTrainingJob("api");
        // Set 5-minute cooldown
        await redis.set(
          cdKey,
          new Date(Date.now() + 300_000).toISOString(),
          "EX",
          300,
        );
        res.writeHead(202);
        res.end(
          JSON.stringify({ status: "ml-training-started", jobId: job.id }),
        );
      } catch (err) {
        log.error({ err }, "Failed to start ML training job");
        const status = err.message.includes("Another ML training") ? 409 : 500;
        res.writeHead(status);
        res.end(JSON.stringify({ error: err.message }));
      }
      return;
    }

    // ─── Backtest API ────────────────────────────────────────
    // Run backtest (requires API key)
    if (url.pathname === "/api/backtest/run" && req.method === "POST") {
      if (!checkAuth(req)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: "Forbidden: invalid API key" }));
        return;
      }
      let body = "";
      for await (const chunk of req) body += chunk;
      const { strategy, timerange } = JSON.parse(body || "{}");
      const tr = timerange || getDefaultTimerange();
      const strats =
        !strategy || strategy === "all"
          ? [
              "A52Strategy",
              "OPTStrategy",
              "A51Strategy",
              "A31Strategy",
              "AdaptiveMLStrategy",
            ]
          : [strategy];

      log.info({ strategies: strats, timerange: tr }, "Backtest triggered");
      discord.sendAlert(
        "info",
        `🏃 Backtest started: ${strats.join(", ")} | Range: ${tr}`,
      );

      // Run backtests in background (delegated to job-manager)
      runBacktests(strats, tr, redis, discord).catch((err) => {
        log.error({ err }, "Backtest pipeline failed");
        discord.sendAlert("critical", `❌ Backtest failed: ${err.message}`);
      });

      res.writeHead(202);
      res.end(
        JSON.stringify({
          status: "backtest-started",
          strategies: strats,
          timerange: tr,
        }),
      );
      return;
    }

    // Get backtest results
    if (url.pathname === "/api/backtest/results") {
      const results = await getBacktestResults(redis);
      res.writeHead(200);
      res.end(JSON.stringify(results));
      return;
    }

    // Download historical data (requires API key)
    if (url.pathname === "/api/data/download" && req.method === "POST") {
      if (!checkAuth(req)) {
        res.writeHead(403);
        res.end(JSON.stringify({ error: "Forbidden: invalid API key" }));
        return;
      }
      let body = "";
      for await (const chunk of req) body += chunk;
      const { pairs, timeframes, timerange } = JSON.parse(body || "{}");
      const tr = timerange || getDefaultTimerange();
      const pairList = pairs || ["ETH/USDT:USDT"];
      const tfList = timeframes || ["5m", "15m", "1h"];

      log.info(
        { pairs: pairList, timeframes: tfList, timerange: tr },
        "Data download triggered",
      );
      discord.sendAlert(
        "info",
        `📥 Downloading data: ${pairList.join(", ")} | ${tfList.join(", ")} | ${tr}`,
      );

      downloadData(pairList, tfList, tr, discord).catch((err) => {
        log.error({ err }, "Data download failed");
      });

      res.writeHead(202);
      res.end(
        JSON.stringify({
          status: "download-started",
          pairs: pairList,
          timeframes: tfList,
          timerange: tr,
        }),
      );
      return;
    }

    // Discord status
    if (url.pathname === "/api/discord/status") {
      res.writeHead(200);
      res.end(JSON.stringify(discord.getStatus()));
      return;
    }

    // ─── Diagnostics API ───────────────────────────────────────
    // Rejection journal — why the bot didn't trade
    if (url.pathname === "/api/diagnostics/rejections") {
      try {
        const fs = await import("node:fs/promises");
        const raw = await fs.readFile(
          "/freqtrade/user_data/ml_models/rejection_journal.json",
          "utf8",
        );
        const entries = JSON.parse(raw);
        const limit = parseInt(url.searchParams.get("limit") || "50", 10);
        // Return most recent entries
        const recent = Array.isArray(entries)
          ? entries.slice(-limit).reverse()
          : [];
        res.writeHead(200);
        res.end(JSON.stringify(recent));
      } catch (err) {
        // File may not exist yet — return empty
        res.writeHead(200);
        res.end(JSON.stringify([]));
      }
      return;
    }

    // ─── Model Registry API ────────────────────────────────────
    if (url.pathname === "/api/ml/registry") {
      try {
        const fs = await import("node:fs/promises");
        const raw = await fs.readFile(
          "/freqtrade/user_data/ml_models/registry.json",
          "utf8",
        );
        res.writeHead(200);
        res.end(raw);
      } catch {
        res.writeHead(200);
        res.end(JSON.stringify({ active: null, versions: [] }));
      }
      return;
    }

    // Rollback model version
    if (url.pathname === "/api/ml/rollback" && req.method === "POST") {
      try {
        const body = await new Promise((resolve) => {
          let data = "";
          req.on("data", (c) => (data += c));
          req.on("end", () => resolve(JSON.parse(data)));
        });
        const versionId = body.version_id;
        if (!versionId) {
          res.writeHead(400);
          res.end(JSON.stringify({ error: "version_id required" }));
          return;
        }
        // Delegate to Python model_registry
        const { execSync } = await import("node:child_process");
        const cmd = `cd /freqtrade/user_data/strategies && python3 -c "
from model_registry import ModelRegistry
r = ModelRegistry()
r.rollback('${versionId.replace(/'/g, "")}')
print('OK')
"`;
        execSync(cmd, { timeout: 10000 });
        res.writeHead(200);
        res.end(JSON.stringify({ status: "ok", rolled_back_to: versionId }));
      } catch (err) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: String(err.message || err) }));
      }
      return;
    }

    // ─── Trade Replay API ──────────────────────────────────────
    if (url.pathname === "/api/diagnostics/replay") {
      try {
        const fs = await import("node:fs/promises");
        const raw = await fs.readFile(
          "/freqtrade/user_data/ml_models/trade_replay.json",
          "utf8",
        );
        const entries = JSON.parse(raw);
        const limit = parseInt(url.searchParams.get("limit") || "50", 10);
        const recent = Array.isArray(entries)
          ? entries.slice(-limit).reverse()
          : [];
        res.writeHead(200);
        res.end(JSON.stringify(recent));
      } catch {
        res.writeHead(200);
        res.end(JSON.stringify([]));
      }
      return;
    }

    // ─── Shadow Model Comparison API ───────────────────────────
    if (url.pathname === "/api/ml/shadow") {
      try {
        const fs = await import("node:fs/promises");
        const raw = await fs.readFile(
          "/freqtrade/user_data/ml_models/trade_replay.json",
          "utf8",
        );
        const entries = JSON.parse(raw);
        const all = Array.isArray(entries) ? entries : [];
        const withShadow = all.filter(
          (e) => e.event === "entry" && e.shadow,
        );
        const agrees = withShadow.filter(
          (e) => e.shadow.would_allow === true,
        ).length;
        const disagrees = withShadow.filter(
          (e) => e.shadow.would_allow === false,
        ).length;
        const total = withShadow.length;
        const recent = withShadow.slice(-20).reverse();
        res.writeHead(200);
        res.end(
          JSON.stringify({
            total,
            agrees,
            disagrees,
            agreement_rate:
              total > 0 ? +(agrees / total).toFixed(4) : null,
            recent,
          }),
        );
      } catch {
        res.writeHead(200);
        res.end(
          JSON.stringify({
            total: 0,
            agrees: 0,
            disagrees: 0,
            agreement_rate: null,
            recent: [],
          }),
        );
      }
      return;
    }

    // ─── Risk Cockpit API ──────────────────────────────────────
    if (url.pathname === "/api/risk/cockpit") {
      try {
        // Aggregate risk metrics from FT API
        const [status, profit, performance] = await Promise.all([
          ftApi("/status"),
          ftApi("/profit"),
          ftApi("/performance"),
        ]);

        const openTrades = Array.isArray(status) ? status : [];
        const totalExposure = openTrades.reduce(
          (sum, t) => sum + Math.abs(t.stake_amount || 0),
          0,
        );
        const pairExposure = {};
        for (const t of openTrades) {
          const p = t.pair || "unknown";
          pairExposure[p] = (pairExposure[p] || 0) + Math.abs(t.stake_amount || 0);
        }
        const maxConcentration = Math.max(0, ...Object.values(pairExposure));
        const worstCase = openTrades.reduce(
          (sum, t) => sum + Math.abs(t.stake_amount || 0) * Math.abs(t.stoploss || 0.025),
          0,
        );

        // Model drift check
        let drift = { status: "unknown", drifted: false };
        try {
          const fs = await import("node:fs/promises");
          const reg = JSON.parse(
            await fs.readFile("/freqtrade/user_data/ml_models/registry.json", "utf8"),
          );
          const active = reg.versions?.find((v) => v.version_id === reg.active);
          drift = {
            status: active ? "tracked" : "untracked",
            drifted: false,
            active_version: reg.active,
            active_since: active?.timestamp,
            params_hash: active?.params_hash,
          };
        } catch {
          // Registry doesn't exist yet
        }

        res.writeHead(200);
        res.end(
          JSON.stringify({
            open_trades: openTrades.length,
            gross_exposure: totalExposure,
            pair_exposure: pairExposure,
            max_concentration: maxConcentration,
            worst_case_loss: worstCase,
            max_drawdown: profit?.max_drawdown || 0,
            max_drawdown_abs: profit?.max_drawdown_abs || 0,
            model_drift: drift,
          }),
        );
      } catch (err) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: String(err.message || err) }));
      }
      return;
    }

    // ─── Benchmark Centre API ───────────────────────────────────
    if (url.pathname === "/api/benchmark") {
      try {
        const [profit, performance, balance] = await Promise.all([
          ftApi("/profit"),
          ftApi("/performance"),
          ftApi("/balance"),
        ]);

        // Strategy returns
        const stratReturn = profit?.profit_all_percent || 0;
        const tradingDays = profit?.trading_volume
          ? Math.max(1, Math.ceil((Date.now() - new Date(profit?.first_trade_timestamp || Date.now()).getTime()) / 86400000))
          : 30;

        // Compute annualised metrics
        const annFactor = 365 / tradingDays;
        const sharpe = profit?.sharpe || 0;
        const sortino = profit?.sortino || 0;
        const maxDD = profit?.max_drawdown || 0;
        const calmar = maxDD > 0 ? (stratReturn * annFactor) / (maxDD * 100) : 0;

        // Buy-and-hold benchmark (from performance endpoint)
        const pairs = Array.isArray(performance) ? performance : [];
        const pairBenchmarks = {};
        for (const p of pairs) {
          pairBenchmarks[p.pair] = {
            trades: p.count,
            profit_pct: p.profit,
          };
        }

        // HODL comparison stub — in dry-run we can't get exact price history,
        // so we report strategy vs zero (cash) as baseline
        const benchmarks = {
          cash: { return_pct: 0, label: "Cash (0%)" },
          strategy: {
            return_pct: stratReturn,
            label: `CC R2 Short (${stratReturn.toFixed(2)}%)`,
          },
        };

        res.writeHead(200);
        res.end(JSON.stringify({
          strategy_return_pct: stratReturn,
          trading_days: tradingDays,
          sharpe,
          sortino,
          calmar: parseFloat(calmar.toFixed(4)),
          max_drawdown_pct: (maxDD * 100).toFixed(2),
          profit_factor: profit?.profit_factor || 0,
          win_rate: profit?.winrate || 0,
          expectancy: profit?.expectancy || 0,
          trade_count: profit?.trade_count || 0,
          closed_trades: profit?.closed_trade_count || 0,
          benchmarks,
          pair_breakdown: pairBenchmarks,
        }));
      } catch (err) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: String(err.message || err) }));
      }
      return;
    }

    // ─── Kill-Switch API ─────────────────────────────────────────
    if (url.pathname === "/api/kill-switch") {
      const ksPath = "/freqtrade/user_data/ml_models/kill_switch";
      const fs = await import("node:fs/promises");

      if (req.method === "GET") {
        try {
          await fs.access(ksPath);
          const content = await fs.readFile(ksPath, "utf8");
          let info = {};
          try { info = JSON.parse(content); } catch { info = { raw: content }; }
          res.writeHead(200);
          res.end(JSON.stringify({ active: true, ...info }));
        } catch {
          res.writeHead(200);
          res.end(JSON.stringify({ active: false }));
        }
        return;
      }

      if (req.method === "POST") {
        if (!isAuthed) {
          res.writeHead(403);
          res.end(JSON.stringify({ error: "API key required for kill-switch" }));
          return;
        }
        let body = "";
        for await (const chunk of req) body += chunk;
        let payload = {};
        try { payload = JSON.parse(body); } catch { /* empty */ }

        const activate = payload.active !== false; // default = activate
        if (activate) {
          const info = JSON.stringify({
            activated_at: new Date().toISOString(),
            reason: payload.reason || "operator_triggered",
            source: "api",
          });
          await fs.writeFile(ksPath, info, "utf8");
          log.warn("🛑 KILL SWITCH ACTIVATED via API");
          res.writeHead(200);
          res.end(JSON.stringify({ active: true, message: "Kill switch activated" }));
        } else {
          try { await fs.unlink(ksPath); } catch { /* already gone */ }
          log.info("✅ Kill switch deactivated via API");
          res.writeHead(200);
          res.end(JSON.stringify({ active: false, message: "Kill switch deactivated" }));
        }
        return;
      }
    }

    res.writeHead(404);
    res.end(JSON.stringify({ error: "Not found" }));
  } catch (err) {
    log.error({ err }, "API error");
    res.writeHead(500);
    res.end(JSON.stringify({ error: err.message }));
  }
});

// ─── Startup ───────────────────────────────────────────────────
async function main() {
  log.info("🚀 CC Trading Team Agent Coordinator starting...");
  log.info(`📡 Freqtrade API: ${FREQTRADE_API}`);
  log.info(`🗄️  Redis: ${REDIS_URL}`);

  // ── Startup Validation ───────────────────────────────────
  const warnings = [];
  if (!API_KEY && !ALLOW_OPEN_AUTH) {
    warnings.push("ML_TRAIN_API_KEY not set — mutating API endpoints are BLOCKED. Set ALLOW_OPEN_AUTH=true for dev mode.");
  }
  if (!API_KEY && ALLOW_OPEN_AUTH) {
    warnings.push("ALLOW_OPEN_AUTH=true with no API key — mutating endpoints are OPEN (dev mode only!)");
  }
  if (FT_PASS === "SuperSecure123") {
    warnings.push("Freqtrade API using default password — set FREQTRADE_PASS in .env for production");
  }
  if (!process.env.DISCORD_TOKEN) {
    warnings.push("DISCORD_TOKEN not set — Discord bot will not connect");
  }
  for (const w of warnings) log.warn(`⚠️  ${w}`);
  if (warnings.length) log.info(`${warnings.length} startup warning(s) — review .env config`);

  // Wait for Redis
  await redis.ping();
  log.info("✅ Redis connected");

  // ── Startup Self-Test (delegated to ft-client) ──────────
  await selfTestFT();

  // Initialize Discord bot
  const discordOk = await discord.initDiscord();
  const discordStatus = discord.getStatus();
  log.info(`Discord status: ${JSON.stringify(discordStatus)}`);

  // Store initial agent state
  for (const agent of agents) {
    await redis.hset("trading:agents", agent.id, JSON.stringify(agent));
  }

  // Start scheduler
  startScheduler();
  log.info(`⏰ ${jobs.length} agent schedules active`);

  // Run all agents once on startup (after 10s delay for Freqtrade)
  setTimeout(async () => {
    log.info("🏁 Running initial agent sweep...");
    for (const agent of agents) {
      await executeAgent(agent);
    }
  }, 10_000);

  // Start HTTP server
  server.listen(PORT, "0.0.0.0", () => {
    log.info(`🌐 Agent API listening on port ${PORT}`);
  });
}

main().catch((err) => {
  log.fatal({ err }, "Fatal startup error");
  process.exit(1);
});

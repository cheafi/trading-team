/**
 * Agent Coordinator — Orchestrates the 6-agent trading team
 *
 * Architecture inspired by gstack's multi-skill pattern:
 * - Each agent runs on a schedule or event trigger
 * - Results are published to Redis for dashboard consumption
 * - Agents can dispatch sub-tasks to each other
 */
import { createServer } from "node:http";
import { execSync, spawn } from "node:child_process";
import Redis from "ioredis";
import { CronJob } from "cron";
import pino from "pino";
import discord from "./discord-bot.mjs";

const log = pino({
  level: process.env.LOG_LEVEL || "info",
  transport:
    process.env.NODE_ENV !== "production"
      ? { target: "pino-pretty" }
      : undefined,
});

// ─── Config ────────────────────────────────────────────────────
const REDIS_URL = process.env.REDIS_URL || "redis://redis:6379";
const FREQTRADE_API = process.env.FREQTRADE_API || "http://freqtrade:8080";
const FT_USER = process.env.FREQTRADE_API_USER || "freqtrader";
const FT_PASS = process.env.FREQTRADE_API_PASSWORD || "SuperSecure123";
const PORT = parseInt(process.env.AGENT_PORT || "3001", 10);
const TZ = process.env.TZ || "Asia/Hong_Kong";

// ─── Redis ─────────────────────────────────────────────────────
const redis = new Redis(REDIS_URL, {
  retryStrategy: (times) => Math.min(times * 200, 5000),
  maxRetriesPerRequest: 3,
});

redis.on("connect", () => log.info("Redis connected"));
redis.on("error", (err) => log.error({ err }, "Redis error"));

// ─── Freqtrade API Helper ──────────────────────────────────────
async function ftApi(endpoint, method = "GET", body = null) {
  const url = `${FREQTRADE_API}/api/v1${endpoint}`;
  const headers = {
    Authorization:
      "Basic " + Buffer.from(`${FT_USER}:${FT_PASS}`).toString("base64"),
    "Content-Type": "application/json",
  };

  try {
    const res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      log.warn({ status: res.status, endpoint }, "Freqtrade API error");
      return null;
    }
    return await res.json();
  } catch (err) {
    log.error({ err, endpoint }, "Freqtrade API call failed");
    return null;
  }
}

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
  log.info(`[${agent.id}] Checking backtest metrics...`);

  // Pull pair performance from the running bot
  // Note: /performance returns per-pair stats, not per-strategy
  const performance = await ftApi("/performance");
  const strategies = [
    "A52Strategy",
    "OPTStrategy",
    "A51Strategy",
    "A31Strategy",
  ];

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
    },
    summary: `${strategies.length} strategies monitored | ${performance?.length || 0} pairs tracked`,
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
  const pair = "ETH/USDT:USDT";

  // Portfolio posture: derived from open trade directions
  // (not an independent market analysis — requires candle data for that)
  const longTrades = status?.filter((t) => !t.is_short)?.length || 0;
  const shortTrades = status?.filter((t) => t.is_short)?.length || 0;

  const posture =
    longTrades > shortTrades
      ? "NET_LONG"
      : shortTrades > longTrades
        ? "NET_SHORT"
        : "FLAT";

  const finding = {
    timestamp: new Date().toISOString(),
    agent: agent.id,
    type: "market-scan",
    data: {
      pair,
      posture,
      longTrades,
      shortTrades,
      timestamp: Date.now(),
    },
    summary: `${pair} posture: ${posture} (L:${longTrades} S:${shortTrades})`,
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

// Spawn a background ML training job, stream logs to Redis, and persist job state.
async function startTrainingJob(source = "api") {
  const jobId =
    Date.now().toString() + "-" + Math.random().toString(36).slice(2, 8);
  const summaryKey = "trading:job:ml_training"; // current job summary
  const jobLogsKey = `trading:jobs:ml_training:logs:${jobId}`;
  const resultsKey = `trading:jobs:ml_training:results`;
  const lockKey = "trading:job:ml_training_lock";

  // Try to acquire a lock (prevent concurrent training runs)
  const got = await redis.set(lockKey, jobId, "NX", "EX", 60 * 60); // 1h TTL
  if (!got) {
    const existing = await redis.get(lockKey);
    throw new Error(
      `Another ML training job is running (${existing || "unknown"})`,
    );
  }

  // Prefer container-safe script (runs ml_optimizer.py directly)
  const containerScript = "/app/scripts/ml-train-container.sh";
  const hostScript = "/app/scripts/ml-train.sh";
  const fs = await import("node:fs/promises");
  let cmd, args;
  try {
    const cst = await fs.stat(containerScript).catch(() => null);
    const hst = await fs.stat(hostScript).catch(() => null);
    if (cst && cst.isFile()) {
      cmd = "stdbuf";
      args = ["-oL", "-eL", "bash", containerScript];
    } else if (hst && hst.isFile()) {
      cmd = "stdbuf";
      args = ["-oL", "-eL", "bash", hostScript];
    } else {
      cmd = "sh";
      args = [
        "-c",
        "echo 'ML training starting (simulation)'; for i in 1 2 3 4 5; do echo \"[ML] step $i - processing...\"; sleep 1; done; echo 'ML training finished'",
      ];
    }
  } catch (e) {
    cmd = "sh";
    args = [
      "-c",
      "echo 'ML training starting (simulation)'; for i in 1 2 3 4 5; do echo \"[ML] step $i - processing...\"; sleep 1; done; echo 'ML training finished'",
    ];
  }

  let child;
  try {
    child = spawn(cmd, args, {
      cwd: "/app",
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (err) {
    // Release lock on spawn failure
    await redis.del(lockKey).catch(() => {});
    throw new Error("Failed to spawn training job: " + err.message);
  }

  const job = {
    id: jobId,
    status: "running",
    startedAt: new Date().toISOString(),
    pid: child.pid,
    source,
  };

  // Persist summary and index
  await redis.set(summaryKey, JSON.stringify(job));
  await redis.lpush(resultsKey, JSON.stringify(job));
  await redis.ltrim(resultsKey, 0, 199);

  const pushLog = async (line) => {
    try {
      await redis.lpush(jobLogsKey, line);
      await redis.ltrim(jobLogsKey, 0, 999);
      await redis.publish(
        "trading:jobs:ml_training",
        JSON.stringify({ jobId, line }),
      );
    } catch (e) {
      log.warn({ err: e }, "Failed to push training log to Redis");
    }
  };

  child.stdout.on("data", (buf) => {
    const lines = buf.toString().split(/\r?\n/).filter(Boolean);
    for (const l of lines) pushLog(l);
  });
  child.stderr.on("data", (buf) => {
    const lines = buf.toString().split(/\r?\n/).filter(Boolean);
    for (const l of lines) pushLog(`[ERR] ${l}`);
  });

  child.on("exit", async (code, signal) => {
    job.status = code === 0 ? "finished" : "failed";
    job.exitCode = code;
    job.signal = signal;
    job.finishedAt = new Date().toISOString();
    try {
      // Replace the running entry with the final state
      await redis.set(summaryKey, JSON.stringify(job));
      // Update the first element (running snapshot) to finished
      await redis.lset(resultsKey, 0, JSON.stringify(job));
      await redis.publish(
        "trading:jobs:ml_training:finished",
        JSON.stringify(job),
      );
    } catch (e) {
      log.warn({ err: e }, "Failed to persist training job result");
    }
    // Release lock
    try {
      await redis.del(lockKey);
    } catch (e) {}
    log.info({ jobId, code, signal }, "ML training job finished");

    // After successful training, refresh ML state in Redis
    // so the dashboard immediately reflects new params.
    if (code === 0) {
      try {
        const mlAgent = agents.find((a) => a.id === "ml-optimizer");
        if (mlAgent) {
          log.info("Refreshing ML state after successful training...");
          await runMLStateRefresh(mlAgent);
        }
      } catch (e) {
        log.warn({ err: e }, "Failed to refresh ML state after training");
      }
    }

    // Discord notification
    if (code === 0) {
      discord
        .sendAlert("success", `✅ ML training complete (job ${jobId})`)
        .catch(() => {});
    } else {
      const msg = `❌ ML training FAILED (job ${jobId}, exit=${code})`;
      discord.sendAlert("critical", msg).catch(() => {});
      // Also publish to Redis alerts channel
      redis
        .publish(
          "trading:alerts",
          JSON.stringify({
            alerts: [msg],
            riskLevel: "HIGH",
          }),
        )
        .catch(() => {});
    }
  });

  log.info({ jobId, pid: child.pid }, "Started ML training job");
  return job;
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
const ALLOWED_ORIGINS = (
  process.env.CORS_ORIGINS || "http://localhost:3000,http://dashboard:3000"
)
  .split(",")
  .map((s) => s.trim());

function checkAuth(req) {
  if (!API_KEY) return true; // no key configured = open (dev mode)
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
        const job = await startTrainingJob("api");
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

      // Run backtests in background
      runBacktests(strats, tr).catch((err) => {
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
      const results = await getBacktestResults();
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

      downloadData(pairList, tfList, tr).catch((err) => {
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

    res.writeHead(404);
    res.end(JSON.stringify({ error: "Not found" }));
  } catch (err) {
    log.error({ err }, "API error");
    res.writeHead(500);
    res.end(JSON.stringify({ error: err.message }));
  }
});

// ─── Backtest Helpers ──────────────────────────────────────────
function getDefaultTimerange() {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 6);
  const fmt = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  return `${fmt(start)}-${fmt(end)}`;
}

async function downloadData(pairs, timeframes, timerange) {
  // Sanitize inputs
  const safePat = /^[a-zA-Z0-9/:_\-. ]+$/;
  const safePairs = pairs.filter((p) => safePat.test(p));
  const safeTfs = timeframes.filter((t) => safePat.test(t));
  const safeTimerange = /^\d{8}-\d{8}$/.test(timerange)
    ? timerange
    : "20240101-20241231";
  if (!safePairs.length || !safeTfs.length) {
    throw new Error("Invalid input characters in download params");
  }

  const args = [
    "compose", "run", "--rm", "freqtrade",
    "download-data",
    "--config", "/freqtrade/config/config.json",
    "--pairs", ...safePairs,
    "--timeframes", ...safeTfs,
    "--timerange", safeTimerange,
  ];

  return new Promise((resolve, reject) => {
    log.info({ args }, "Downloading data...");
    const proc = spawn("docker", args, { cwd: "/app", timeout: 600_000 });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => { stdout += d; });
    proc.stderr.on("data", (d) => { stderr += d; });
    proc.on("close", (code) => {
      if (code !== 0) {
        log.error({ code, stderr }, "Data download failed");
        reject(new Error(`download-data exited with code ${code}: ${stderr}`));
        return;
      }
      log.info("Data download complete");
      discord.sendAlert(
        "success",
        `✅ Data download complete: ${pairs.join(", ")}`,
      );
      resolve(stdout);
    });
    proc.on("error", (err) => {
      log.error({ err }, "Data download spawn error");
      reject(err);
    });
  });
}

async function runBacktests(strategies, timerange) {
  const results = [];

  for (const strategy of strategies) {
    log.info({ strategy, timerange }, "Running backtest...");

    try {
      // Sanitize strategy name and timerange to prevent command injection
      const safeStrategy = strategy.replace(/[^a-zA-Z0-9_]/g, "");
      const safeTimerange = /^\d{8}-\d{8}$/.test(timerange)
        ? timerange
        : "20240101-20241231";
      const output = await new Promise((resolve, reject) => {
        const args = [
          "compose", "run", "--rm", "freqtrade",
          "backtesting",
          "--config", "/freqtrade/config/config_backtest.json",
          "--strategy", safeStrategy,
          "--strategy-path", "/freqtrade/user_data/strategies",
          "--timerange", safeTimerange,
          "--timeframe", "5m",
          "--enable-protections",
          "--export", "trades",
        ];
        const proc = spawn("docker", args, { cwd: "/app", timeout: 600_000 });
        let out = "";
        proc.stdout.on("data", (d) => { out += d; });
        proc.stderr.on("data", (d) => { out += d; });
        proc.on("close", (code) => {
          if (code !== 0) reject(new Error(`backtesting exited ${code}: ${out.slice(-500)}`));
          else resolve(out);
        });
        proc.on("error", reject);
      });

      // Parse backtest output
      const result = parseBacktestOutput(output, strategy, timerange);
      results.push(result);

      // Store in Redis
      await redis.lpush("trading:backtest:results", JSON.stringify(result));
      await redis.ltrim("trading:backtest:results", 0, 99);

      // Notify Discord
      await discord.sendBacktestResult(result);

      log.info({ strategy, profit: result.profit }, "Backtest complete");
    } catch (err) {
      log.error({ err, strategy }, "Backtest failed");
      results.push({
        strategy,
        timerange,
        error: err.message,
        timestamp: new Date().toISOString(),
      });
    }
  }

  // Summary to Discord
  const totalProfit = results
    .filter((r) => r.profit)
    .reduce((s, r) => s + (r.profit || 0), 0);
  await discord.sendAlert(
    totalProfit >= 0 ? "success" : "warning",
    `🏁 Backtest suite complete!\n${results.map((r) => `• **${r.strategy}**: ${r.profit?.toFixed(2) || "ERROR"}% profit, ${r.totalTrades || 0} trades`).join("\n")}`,
  );

  return results;
}

function parseBacktestOutput(output, strategy, timerange) {
  const lines = output.split("\n");
  let profit = 0,
    winRate = 0,
    maxDrawdown = 0,
    totalTrades = 0,
    sharpe = 0;

  for (const line of lines) {
    const profitMatch = line.match(/Total profit\s+[\d.]+\s+.*?([\-\d.]+)\s*%/);
    if (profitMatch) profit = parseFloat(profitMatch[1]);

    const winMatch = line.match(/Win.*?([\d.]+)\s*%/);
    if (winMatch) winRate = parseFloat(winMatch[1]);

    const ddMatch = line.match(/Max.*?[Dd]rawdown.*?([\d.]+)\s*%/);
    if (ddMatch) maxDrawdown = parseFloat(ddMatch[1]);

    const tradeMatch = line.match(/Total.*?trades.*?(\d+)/);
    if (tradeMatch) totalTrades = parseInt(tradeMatch[1]);

    const sharpeMatch = line.match(/Sharpe.*?([\-\d.]+)/);
    if (sharpeMatch) sharpe = parseFloat(sharpeMatch[1]);
  }

  return {
    strategy,
    timerange,
    profit,
    winRate,
    maxDrawdown,
    totalTrades,
    sharpe,
    timestamp: new Date().toISOString(),
  };
}

async function getBacktestResults() {
  try {
    const raw = await redis.lrange("trading:backtest:results", 0, 49);
    return raw.map((r) => JSON.parse(r));
  } catch {
    return [];
  }
}

// ─── Startup ───────────────────────────────────────────────────
async function main() {
  log.info("🚀 CC Trading Team Agent Coordinator starting...");
  log.info(`📡 Freqtrade API: ${FREQTRADE_API}`);
  log.info(`🗄️  Redis: ${REDIS_URL}`);

  // Wait for Redis
  await redis.ping();
  log.info("✅ Redis connected");

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

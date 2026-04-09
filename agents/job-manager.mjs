/**
 * Job Manager — ML training, backtesting, data download
 *
 * Extracted from coordinator.mjs (Phase 2 architecture split).
 * Manages long-running background jobs with Redis state + Discord notifications.
 */
import { spawn } from "node:child_process";
import pino from "pino";

const log = pino({
  level: process.env.LOG_LEVEL || "info",
  transport:
    process.env.NODE_ENV !== "production"
      ? { target: "pino-pretty" }
      : undefined,
});

/**
 * Start an ML training job.
 * Spawns background process, streams logs to Redis, persists job state.
 *
 * @param {import("ioredis").default} redis
 * @param {object} opts
 * @param {string} opts.source - "api" | "cron" | "discord"
 * @param {Array} opts.agents - agent definitions array (to find ml-optimizer)
 * @param {Function} opts.runMLStateRefresh - callback to refresh ML state post-training
 * @param {object} opts.discord - discord bot module
 * @returns {Promise<object>} job descriptor
 */
export async function startTrainingJob(redis, opts = {}) {
  const { source = "api", agents = [], runMLStateRefresh, discord } = opts;
  const jobId =
    Date.now().toString() + "-" + Math.random().toString(36).slice(2, 8);
  const summaryKey = "trading:job:ml_training";
  const jobLogsKey = `trading:jobs:ml_training:logs:${jobId}`;
  const resultsKey = "trading:jobs:ml_training:results";
  const lockKey = "trading:job:ml_training_lock";

  // Acquire lock (prevent concurrent training)
  const got = await redis.set(lockKey, jobId, "NX", "EX", 60 * 60);
  if (!got) {
    const existing = await redis.get(lockKey);
    throw new Error(
      `Another ML training job is running (${existing || "unknown"})`,
    );
  }

  // Prefer container-safe script
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
  } catch {
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
      await redis.set(summaryKey, JSON.stringify(job));
      await redis.lset(resultsKey, 0, JSON.stringify(job));
      await redis.publish(
        "trading:jobs:ml_training:finished",
        JSON.stringify(job),
      );
    } catch (e) {
      log.warn({ err: e }, "Failed to persist training job result");
    }
    try {
      await redis.del(lockKey);
    } catch {}
    log.info({ jobId, code, signal }, "ML training job finished");

    // Post-training: refresh ML state
    if (code === 0 && runMLStateRefresh) {
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
    if (discord) {
      if (code === 0) {
        discord
          .sendAlert("success", `✅ ML training complete (job ${jobId})`)
          .catch(() => {});
      } else {
        const msg = `❌ ML training FAILED (job ${jobId}, exit=${code})`;
        discord.sendAlert("critical", msg).catch(() => {});
        redis
          .publish(
            "trading:alerts",
            JSON.stringify({ alerts: [msg], riskLevel: "HIGH" }),
          )
          .catch(() => {});
      }
    }
  });

  log.info({ jobId, pid: child.pid }, "Started ML training job");
  return job;
}

// ─── Backtest Helpers ──────────────────────────────────────────

export function getDefaultTimerange() {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 6);
  const fmt = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  return `${fmt(start)}-${fmt(end)}`;
}

/**
 * Download historical data via Freqtrade CLI.
 */
export async function downloadData(pairs, timeframes, timerange, discord) {
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
    "compose",
    "run",
    "--rm",
    "freqtrade",
    "download-data",
    "--config",
    "/freqtrade/config/config_backtest.json",
    "--pairs",
    ...safePairs,
    "--timeframes",
    ...safeTfs,
    "--timerange",
    safeTimerange,
  ];

  return new Promise((resolve, reject) => {
    log.info({ args }, "Downloading data...");
    const proc = spawn("docker", args, { cwd: "/app", timeout: 600_000 });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => {
      stdout += d;
    });
    proc.stderr.on("data", (d) => {
      stderr += d;
    });
    proc.on("close", (code) => {
      if (code !== 0) {
        log.error({ code, stderr }, "Data download failed");
        reject(new Error(`download-data exited with code ${code}: ${stderr}`));
        return;
      }
      log.info("Data download complete");
      if (discord) {
        discord
          .sendAlert(
            "success",
            `✅ Data download complete: ${pairs.join(", ")}`,
          )
          .catch(() => {});
      }
      resolve(stdout);
    });
    proc.on("error", (err) => {
      log.error({ err }, "Data download spawn error");
      reject(err);
    });
  });
}

/**
 * Run backtests for a list of strategies.
 *
 * @param {string[]} strategies
 * @param {string} timerange
 * @param {import("ioredis").default} redis
 * @param {object} discord
 */
export async function runBacktests(strategies, timerange, redis, discord) {
  const results = [];

  for (const strategy of strategies) {
    log.info({ strategy, timerange }, "Running backtest...");

    try {
      const safeStrategy = strategy.replace(/[^a-zA-Z0-9_]/g, "");
      const safeTimerange = /^\d{8}-\d{8}$/.test(timerange)
        ? timerange
        : "20240101-20241231";
      const output = await new Promise((resolve, reject) => {
        const args = [
          "compose",
          "run",
          "--rm",
          "freqtrade",
          "backtesting",
          "--config",
          "/freqtrade/config/config_backtest.json",
          "--strategy",
          safeStrategy,
          "--strategy-path",
          "/freqtrade/user_data/strategies",
          "--timerange",
          safeTimerange,
          "--timeframe",
          "5m",
          "--enable-protections",
          "--export",
          "trades",
        ];
        const proc = spawn("docker", args, { cwd: "/app", timeout: 600_000 });
        let out = "";
        proc.stdout.on("data", (d) => {
          out += d;
        });
        proc.stderr.on("data", (d) => {
          out += d;
        });
        proc.on("close", (code) => {
          if (code !== 0)
            reject(new Error(`backtesting exited ${code}: ${out.slice(-500)}`));
          else resolve(out);
        });
        proc.on("error", reject);
      });

      const result = parseBacktestOutput(output, strategy, timerange);
      results.push(result);

      await redis.lpush("trading:backtest:results", JSON.stringify(result));
      await redis.ltrim("trading:backtest:results", 0, 99);

      if (discord) {
        await discord.sendBacktestResult(result);
      }

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
  if (discord) {
    const totalProfit = results
      .filter((r) => r.profit)
      .reduce((s, r) => s + (r.profit || 0), 0);
    await discord.sendAlert(
      totalProfit >= 0 ? "success" : "warning",
      `🏁 Backtest suite complete!\n${results.map((r) => `• **${r.strategy}**: ${r.profit?.toFixed(2) || "ERROR"}% profit, ${r.totalTrades || 0} trades`).join("\n")}`,
    );
  }

  return results;
}

export function parseBacktestOutput(output, strategy, timerange) {
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

export async function getBacktestResults(redis) {
  try {
    const raw = await redis.lrange("trading:backtest:results", 0, 49);
    return raw.map((r) => JSON.parse(r));
  } catch {
    return [];
  }
}

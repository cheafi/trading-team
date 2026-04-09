/**
 * Freqtrade API Client — authenticated REST wrapper
 *
 * Extracted from coordinator.mjs (Phase 2 architecture split).
 * All FT API calls go through this module.
 */
import pino from "pino";

const log = pino({
  level: process.env.LOG_LEVEL || "info",
  transport:
    process.env.NODE_ENV !== "production"
      ? { target: "pino-pretty" }
      : undefined,
});

// ─── Config ────────────────────────────────────────────────────
export const FREQTRADE_API =
  process.env.FREQTRADE_API || "http://freqtrade:8080";
export const FT_USER = process.env.FREQTRADE_API_USER || "freqtrader";
export const FT_PASS = process.env.FREQTRADE_API_PASSWORD || "SuperSecure123";

// ─── Authenticated FT API helper ───────────────────────────────
export async function ftApi(endpoint, method = "GET", body = null) {
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

/**
 * Startup self-test: verify FT API reachable + log config summary.
 * @returns {boolean} true if FT API is reachable
 */
export async function selfTestFT() {
  log.info("🔍 Running FT API self-test...");
  let healthy = false;
  for (let attempt = 1; attempt <= 5; attempt++) {
    const ping = await ftApi("/ping");
    if (ping && ping.status === "pong") {
      healthy = true;
      log.info("✅ Freqtrade API reachable");
      break;
    }
    log.warn(`⏳ FT API not ready (attempt ${attempt}/5) — retrying in 5s...`);
    await new Promise((r) => setTimeout(r, 5000));
  }
  if (!healthy) {
    log.error(
      "❌ Freqtrade API unreachable after 5 attempts — agents will retry individually",
    );
    return false;
  }

  // Config parity check
  try {
    const show = await ftApi("/show_config");
    if (show) {
      const checks = [];
      if (show.dry_run !== undefined) {
        checks.push(`mode=${show.dry_run ? "dry_run" : "LIVE"}`);
        if (!show.dry_run) log.warn("⚠️  Freqtrade is in LIVE mode!");
      }
      if (show.trading_mode) checks.push(`trading_mode=${show.trading_mode}`);
      if (show.stake_currency) checks.push(`stake=${show.stake_currency}`);
      if (show.timeframe) checks.push(`tf=${show.timeframe}`);
      if (show.max_open_trades)
        checks.push(`max_trades=${show.max_open_trades}`);
      log.info(`✅ FT config: ${checks.join(", ")}`);
    }
  } catch (err) {
    log.warn({ err }, "Could not verify FT config parity");
  }

  return true;
}

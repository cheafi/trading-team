# Cheafi — AI Coding Agent Instructions

## System Identity (be honest)

**Cheafi** is currently an **ETH/USDT 5m R2 short specialist** — a single-pair, single-regime trading bot in research/paper-trading stage.

The multi-regime infrastructure exists but only R2 (RANGING, short-only) is active in production. Do NOT describe this system as a "multi-regime adaptive engine" unless other regimes are re-enabled in `populate_entry_trend()`.

## Architecture

Four Docker services:

| Service | Port | Role |
|---|---|---|
| `freqtrade` | 8080 | Python trading engine — backtesting + live execution |
| `agent-runner` | 3001 | Node.js coordinator — 7 cron-scheduled agents |
| `dashboard` | 3000 | Next.js control panel — consumes agent API |
| `redis` | 6379 | Shared state bus between all services |

## Regime → Strategy Mapping (critical)

**Only R2 (RANGING) short trades are active.** R0/R1/R3 are disabled.

```
R0 TRENDING_UP   → DISABLED (fallback: A31)
R1 TRENDING_DOWN → DISABLED (fallback: A51)
R2 RANGING       → A52 (short only) ← THE ONLY ACTIVE REGIME
R3 VOLATILE      → DISABLED (fallback: A52)
```

Regime detection is **rule-based** (ADX/EMA/ATR/BB thresholds). The regime model trained by `ml_optimizer.py` is NOT used by the live strategy — it's dead complexity under research.

AdaptiveMLStrategy hot-reloads `ml_models/best_params.json` every 300s — **never hard-code strategy params in the strategy file itself**.

## ML Pipeline Data Flow

```
backtest_results/*.json → ml_optimizer.py → ml_models/
    ├── regime_model.pkl       (trained but NOT used in live decisions)
    ├── quality_model.pkl      (3-feature session/direction prior — hour, weekday, side)
    ├── best_params.json       (per-regime: c, e, sl, roi_table, kelly_fraction)
    ├── discipline_params.json (cooldown, daily loss limit)
    ├── anti_patterns.json     (toxic hours/days learned from losses)
    └── rejection_journal.json (persisted trade rejection reasons)
```

**Honest ML assessment:**
- Quality model uses `[hour, weekday, is_short]` — a session-direction prior, not deep trade intelligence.
- Regime model is trained but NOT loaded by the live strategy.
- Training via API relearns from existing backtests — it does NOT download fresh data or run new backtests.

## Critical Developer Workflows

```bash
# Start full stack
./scripts/start.sh

# Backtest all strategies
./scripts/backtest-all.sh 20240101-20260101

# Retrain ML models (from existing backtest results)
curl -X POST http://localhost:3001/api/ml/train

# Retrain directly inside container
docker compose exec freqtrade python /freqtrade/user_data/strategies/ml_optimizer.py --retrain

# Tail all logs
docker compose logs -f

# Freqtrade API (creds: freqtrader / SuperSecure123)
curl -u freqtrader:SuperSecure123 http://localhost:8080/api/v1/profit
```

## Project Conventions

- **Futures only, never spot.** Pairs must use `:USDT` suffix: `ETH/USDT:USDT`.
- **`can_short = True` is required** in AdaptiveMLStrategy. Reverting this disables all short trades.
- **5m primary + 15m + 1h confirmation timeframe.** `startup_candle_count = 200` is mandatory.
- Agent coordinator is **ESM (`"type": "module"`)** — use `.mjs` extension and `import`/`export`, not `require()`.
- Dashboard uses **Next.js App Router** (`src/app/`). All data fetching uses `useSWR` hooks from `src/lib/hooks.ts`.
- Redis key pattern: `trading:agents`, `trading:findings`, `trading:alerts`.
- **Decision journal**: every `confirm_trade_entry()` rejection is persisted to `rejection_journal.json` so operators can answer "why didn't the bot trade?"

## Agent Schedules (coordinator.mjs)

| Agent | Cron | What it actually does |
|---|---|---|
| risk-manager | `*/5 * * * *` | Reads DD from FT API, alerts if > 15% |
| signal-engineer | `*/5 * * * *` | Regime detection, entry signals |
| quant-researcher | `*/15 * * * *` | Analyze trade P&L distribution |
| market-analyst | `*/10 * * * *` | ETH volume + trend snapshot |
| backtester | `0 */2 * * *` | Auto backtest on new data |
| ml-optimizer | `0 */2 * * *` | **State refresh only** — reads params, publishes to Redis. Does NOT retrain. |
| security-auditor | `0 */6 * * *` | FT version, health, pair locks |

## Key Files

- `freqtrade/user_data/strategies/AdaptiveMLStrategy.py` — live R2 short specialist
- `freqtrade/user_data/strategies/ml_optimizer.py` — ML training pipeline (2083 lines)
- `freqtrade/user_data/ml_models/best_params.json` — hot-reloaded per-regime params
- `agents/coordinator.mjs` — agent orchestrator + REST API (1150 lines)
- `agents/discord-bot.mjs` — Discord integration
- `freqtrade/config/config.json` — Freqtrade config (dry_run, pairs, API creds)
- `docker-compose.yml` — full stack definition

## Risk Rules (never violate)

- Max drawdown alert: **15%**, emergency halt: **20%**
- Max 4 open positions (`max_open_trades: 4`)
- Minimum edge: **2× round-trip fee** (0.10%) before entering any trade
- Default is `"dry_run": true` — set to `false` only with explicit live keys in `.env`
- R2 regime in `best_params.json` is currently marked `is_robust: false` — treat as research capital only

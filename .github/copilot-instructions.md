# Cheafi — AI Coding Agent Instructions

## Big Picture Architecture

**Cheafi** is a multi-agent algo trading platform for ETH/USDT Futures on Binance. Four Docker services work together:

| Service | Port | Role |
|---|---|---|
| `freqtrade` | 8080 | Python trading engine — backtesting + live execution |
| `agent-runner` | 3001 | Node.js coordinator — 7 cron-scheduled AI agents |
| `dashboard` | 3000 | Next.js control panel — consumes agent API |
| `redis` | 6379 | Shared state bus between all services |

The **AdaptiveMLStrategy** (`freqtrade/user_data/strategies/AdaptiveMLStrategy.py`) is the live strategy. It is a meta-strategy that selects among four sub-strategies (A52, A51, A31, OPT) based on an ML-detected market regime.

## Regime → Strategy Mapping (critical)

**Only R2 (RANGING) short trades are active.** R0/R1/R3 are disabled — they produce more SL losses than ROI wins.

```
R0 TRENDING_UP   → DISABLED (fallback: A31)
R1 TRENDING_DOWN → DISABLED (fallback: A51)
R2 RANGING       → A52 (short only) ← THE ONLY ACTIVE REGIME
R3 VOLATILE      → DISABLED (fallback: A52)
```

The regime model is trained by `ml_optimizer.py` and persisted in `ml_models/regime_model.pkl`. AdaptiveMLStrategy hot-reloads `ml_models/best_params.json` on each candle — **never hard-code strategy params in the strategy file itself**.

## ML Pipeline Data Flow

```
backtest_results/*.json → ml_optimizer.py → ml_models/
    ├── regime_model.pkl      (GradientBoosting regime classifier)
    ├── quality_model.pkl     (GradientBoosting trade quality gate)
    ├── best_params.json      (per-regime: c, e, sl, roi_table, kelly_fraction)
    ├── discipline_params.json (cooldown, daily loss limit)
    └── anti_patterns.json    (toxic hours/days learned from losses)
```

`best_params.json` keys are regime IDs (0-7). The `c` field is position sizing coefficient (0–1), `e` is entry bias (−0.5 to +0.5, negative = short bias).

## Critical Developer Workflows

```bash
# Start full stack
./scripts/start.sh

# Backtest all strategies (default 2024)
./scripts/backtest-all.sh 20240101-20241231

# Single strategy backtest
docker compose run --rm freqtrade backtesting \
  --config /freqtrade/config/config_backtest.json \
  --strategy AdaptiveMLStrategy \
  --strategy-path /freqtrade/user_data/strategies \
  --timerange 20240101-20241231 --timeframe 5m

# Retrain ML models (run inside freqtrade container)
docker compose exec freqtrade python /freqtrade/user_data/strategies/ml_optimizer.py --retrain

# Tail all logs
docker compose logs -f

# Freqtrade API (creds: freqtrader / SuperSecure123)
curl -u freqtrader:SuperSecure123 http://localhost:8080/api/v1/profit
```

## Project Conventions

- **Futures only, never spot.** Pairs must use `:USDT` suffix: `ETH/USDT:USDT`. Config has `"trading_mode": "futures"` + `"margin_mode": "isolated"`.
- **`can_short = True` is required** in AdaptiveMLStrategy. Reverting this disables all short trades.
- **5m primary + 1h confirmation timeframe.** `startup_candle_count = 200` is mandatory.
- Agent coordinator is **ESM (`"type": "module"`)** — use `.mjs` extension and `import`/`export`, not `require()`.
- Dashboard uses **Next.js App Router** (`src/app/`). All data fetching uses `useSWR` hooks from `src/lib/hooks.ts`.
- Redis key pattern: `trading:agents`, `trading:findings`, `trading:alerts` — all agent outputs go through Redis so the dashboard can poll them.

## Agent Schedules (coordinator.mjs)

| Agent | Cron | Function |
|---|---|---|
| risk-manager | `*/5 * * * *` | Monitor DD, halt if > 20% |
| signal-engineer | `*/5 * * * *` | Regime detection, entry signals |
| quant-researcher | `*/15 * * * *` | Analyze trade performance |
| market-analyst | `*/10 * * * *` | ETH macro + volume analysis |
| backtester | `0 */2 * * *` | Auto backtest on new data |
| ml-optimizer | `0 */2 * * *` | Retrain models, update best_params |
| security-auditor | `0 */6 * * *` | FT version, health, pair locks |

## Key Files

- [freqtrade/user_data/strategies/AdaptiveMLStrategy.py](../freqtrade/user_data/strategies/AdaptiveMLStrategy.py) — live meta-strategy (1168 lines)
- [freqtrade/user_data/strategies/ml_optimizer.py](../freqtrade/user_data/strategies/ml_optimizer.py) — full ML training pipeline
- [freqtrade/user_data/ml_models/best_params.json](../freqtrade/user_data/ml_models/best_params.json) — hot-reloaded per-regime params
- [agents/coordinator.mjs](../agents/coordinator.mjs) — agent orchestrator + REST API
- [freqtrade/config/config.json](../freqtrade/config/config.json) — Freqtrade config (dry_run, pairs, API creds)
- [docker-compose.yml](../docker-compose.yml) — full stack definition
- [agents/SOUL.md](../agents/SOUL.md) — team mission and risk values

## Risk Rules (never violate)

- Max drawdown alert: **15%**, emergency halt: **20%**
- Max 4 open positions (`max_open_trades: 4`)
- Minimum edge: **2× round-trip fee** (0.10%) before entering any trade
- Default is `"dry_run": true` — set to `false` only with explicit live keys in `.env`

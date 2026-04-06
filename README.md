# 🐼 CC — ETH/USDT 5m Short Specialist

> Multi-agent algo trading platform for ETH/USDT Futures on Binance.
> Currently running **one active regime** (R2 RANGING, short-only).
> Research / paper-trading stage — not production capital.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard (Next.js)                   │
│           http://localhost:3000 — Dark theme UI           │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │ 🔬   │ │ 📊   │ │ 🛡️   │ │ 📡   │ │ 🌍   │ │ 🔒   │ │
│  │Quant │ │Back- │ │Risk  │ │Signal│ │Market│ │Sec.  │ │
│  │Res.  │ │tester│ │Mgr.  │ │Eng.  │ │Anal. │ │Audit │ │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ │
│     └────────┴────────┴────┬───┴────────┴────────┘      │
│              Agent Coordinator (Node.js :3001)            │
└────────────────────────────┬─────────────────────────────┘
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │ Freqtrade │        │  Redis   │        │ Exchange │
   │  :8080    │        │  :6379   │        │ (Binance)│
   └──────────┘        └──────────┘        └──────────┘
```

| Service | Port | Role |
|---|---|---|
| `freqtrade` | 8080 | Python trading engine — backtesting + live execution |
| `agent-runner` | 3001 | Node.js coordinator — 7 cron-scheduled agents |
| `dashboard` | 3000 | Next.js control panel — consumes agent API |
| `redis` | 6379 | Shared state bus between all services |

## 🚀 Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/cheafi/trading-team.git
cd trading-team
cp .env.example .env    # fill in your keys (optional — dry_run works without)
chmod +x scripts/*.sh

# 2. Start everything
./scripts/start.sh
# — or —
docker compose up -d

# 3. Open dashboard
open http://localhost:3000

# 4. Backtest all strategies
./scripts/backtest-all.sh 20240101-20260101

# 5. Retrain ML models
curl -X POST http://localhost:3001/api/ml/train

# 6. Check Freqtrade API
curl -u freqtrader:SuperSecure123 http://localhost:8080/api/v1/profit

# 7. Tail logs
docker compose logs -f
```

## 📈 Current Live Strategy

**Only R2 (RANGING) short trades are active.** R0/R1/R3 are disabled — they produce more SL losses than ROI wins.

| Regime | Name | Strategy | Direction | Status |
|--------|------|----------|-----------|--------|
| R0 | TRENDING UP | A31 (Squeeze) | — | ⛔ Disabled |
| R1 | TRENDING DOWN | A51 (VWAP) | — | ⛔ Disabled |
| **R2** | **RANGING** | **A52 (Momentum)** | **SHORT only** | ✅ Active |
| R3 | VOLATILE | A52 (Momentum) | — | ⛔ Disabled |

This means the bot is currently an **ETH/USDT 5m R2 short specialist**, not a multi-regime adaptive engine. The multi-regime infrastructure exists and is under research, but only R2 short has demonstrated a viable edge.

## 📊 Sub-Strategies

| # | Strategy | c | e | Style |
|---|----------|------|-------|-------|
| 1 | **A52** | 0.50 | -0.18 | Multi-factor momentum (active in R2) |
| 2 | **OPT** | 0.65 | +0.05 | Ichimoku + SuperTrend |
| 3 | **A51** | 0.35 | 0.00 | VWAP + Order Block scalper |
| 4 | **A31** | 0.80 | -0.10 | Volatility squeeze breakout |

**Parameters:**
- `c` = Position sizing coefficient (0.0-1.0, higher = more aggressive)
- `e` = Entry bias (−0.5 to +0.5, negative = short bias, positive = long bias)

## 🤖 Agent Team

| Agent | Schedule | Function |
|---|---|---|
| Risk Manager | `*/5 * * * *` | Monitor DD, halt if > 20% |
| Signal Engineer | `*/5 * * * *` | Regime detection, entry signals |
| Quant Researcher | `*/15 * * * *` | Analyze trade performance |
| Market Analyst | `*/10 * * * *` | ETH macro + volume analysis |
| Backtester | `0 */2 * * *` | Auto backtest on new data |
| ML State Monitor | `0 */2 * * *` | Refresh ML state to Redis (does NOT retrain) |
| Security Auditor | `0 */6 * * *` | FT version, health, pair locks |

**Note:** The "ML State Monitor" agent reads current params and publishes state to Redis/Discord. It does NOT retrain models. Actual retraining is triggered manually via `curl -X POST :3001/api/ml/train` or the dashboard button.

## 🧠 ML Pipeline

```
backtest_results/*.json → ml_optimizer.py → ml_models/
    ├── regime_model.pkl       (trained but NOT used in live decisions)
    ├── quality_model.pkl      (3-feature session/direction prior)
    ├── best_params.json       (per-regime: c, e, sl, roi_table, kelly)
    ├── discipline_params.json (cooldown, daily loss limit)
    ├── anti_patterns.json     (toxic hours/days from loss analysis)
    └── rejection_journal.json (NEW: persisted trade rejection reasons)
```

**Honest assessment:**
- The quality model uses only `[hour, weekday, is_short]` — it's a session-direction prior, not deep trade intelligence.
- The regime model is trained by `ml_optimizer.py` but NOT loaded or used by the live strategy. Regime detection is rule-based (ADX/EMA/ATR/BB thresholds).
- Training via the API/dashboard button relearns from existing backtests — it does NOT download fresh data or run new backtests.

## 🤖 Discord Bot Setup

1. **Create Discord Application** at [Discord Developer Portal](https://discord.com/developers/applications)
2. **Create Bot** → Copy TOKEN → Enable MESSAGE CONTENT INTENT
3. **Invite Bot** → OAuth2 → Scopes: `bot`, `applications.commands` → Permissions: Send Messages, Embed Links, Read Message History
4. **Configure .env:**
   ```
   DISCORD_BOT_TOKEN=your_bot_token_here
   DISCORD_CHANNEL_NAME=trading-cc
   ```
5. **Test:**
   ```bash
   docker compose restart agent-runner
   curl http://localhost:3001/api/discord/status
   # In Discord: !help
   ```

## 🛡️ Risk Envelope

- **Max drawdown alert:** 15% — emergency halt: 20%
- **Max open positions:** 4
- **Min edge:** 2× round-trip fee (0.10%)
- **Default:** `dry_run: true` — set to `false` only with explicit live keys

## 📁 Project Structure

```
trading-team/
├── agents/                     # Agent orchestration (Node.js ESM)
│   ├── coordinator.mjs         # Main coordinator + REST API
│   ├── discord-bot.mjs         # Discord bot integration
│   └── */SKILL.md              # Per-agent skill configs
├── dashboard/                  # Next.js App Router frontend
│   ├── src/app/                # Pages + API routes
│   ├── src/components/         # React components
│   └── src/lib/                # Hooks & utilities
├── freqtrade/                  # Trading engine
│   ├── config/                 # config.json, config_backtest.json
│   └── user_data/
│       ├── strategies/         # AdaptiveMLStrategy.py, ml_optimizer.py
│       ├── ml_models/          # Trained models + params
│       └── backtest_results/   # Backtest output JSONs
├── scripts/                    # start.sh, backtest-all.sh, ml-train*.sh
├── docs/                       # GitHub Pages site
├── docker-compose.yml          # Full stack orchestration
└── Dockerfile.agents           # Agent runner image
```

## 🔄 Going Live

> ⚠️ Only switch to live trading after extensive backtesting and paper trading.

1. Get Binance API keys (Futures enabled)
2. Edit `.env`: `EXCHANGE_KEY=...`, `EXCHANGE_SECRET=...`
3. Edit `freqtrade/config/config.json`: `"dry_run": false`
4. Restart: `docker compose restart freqtrade`

---

**CC** — a well-instrumented ETH 5m specialist under active research 🐼

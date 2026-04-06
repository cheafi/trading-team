# CC — Development Status & Roadmap

## Current Identity (2026-04-06)

**USDT Futures 5m R2 Short Specialist** — 6 pairs (ETH, BTC, SOL, BNB, XRP, DOGE) — research / paper-trading stage.

### What the system actually does
- Trades 6 pairs on Binance Futures via StaticPairList (isolated margin)
- Only R2 (RANGING) short entries are active — other regimes disabled
- Uses A52 (multi-factor momentum) as primary sub-strategy
- Rule-based regime detection (ADX/EMA/ATR/BB thresholds)
- Kelly-blended position sizing with anti-martingale
- MFE-calibrated trailing stops
- Quality model gate (3-feature session-direction prior)
- Anti-pattern filter (toxic hours/days from loss analysis)
- Decision journal for all trade rejections

### What the system does NOT do (yet)
- Multi-regime live trading (R0/R1/R3 disabled)
- Real-time ML regime classification (trained model exists but unused)
- Deep trade quality intelligence (model uses only hour/weekday/side)
- Auto-download fresh data + rebacktest + retrain pipeline
- The scheduled "ML optimizer" agent refreshes state, does NOT retrain

---

## Backtest Results (Jan 1 – Mar 29, 2026)

| Strategy | Trades | P/L | Drawdown | Market |
|----------|--------|-----|----------|--------|
| AdaptiveMLStrategy | 257 | -0.62% | 0.65% | -29.69% |
| A52 standalone | 1809 | -13.73% | — | -29.69% |

The meta-strategy protects capital effectively during a -30% crash,
but the edge is narrow and R2 is marked `is_robust: false`.

---

## Architecture

### Live Regime Mapping
| ID | Regime | Strategy | Status |
|----|--------|----------|--------|
| R0 | TRENDING_UP | A31 (Squeeze) | ⛔ Disabled |
| R1 | TRENDING_DOWN | A51 (VWAP) | ⛔ Disabled |
| **R2** | **RANGING** | **A52 (Momentum, short-only)** | ✅ Active |
| R3 | VOLATILE | A52 (Momentum) | ⛔ Disabled |

### ML Pipeline (`ml_optimizer.py`)
- Regime model — **GradientBoostingClassifier** (trained but not used live)
- Quality model — **GradientBoostingClassifier** (3 features: hour, weekday, side)
- Walk-forward validation (coarse robustness heuristic, not full replay)
- Anti-pattern detection (toxic hours/days from loss analysis)
- Kelly criterion position sizing

### Agent Schedule
| Agent | Schedule | What it actually does |
|---|---|---|
| Risk Manager | */5 min | Reads DD from FT API, alerts if > 15% |
| Signal Engineer | */5 min | Detects regime, reports entry conditions |
| Quant Researcher | */15 min | Analyzes trade P&L distribution |
| Market Analyst | */10 min | ETH volume + trend snapshot |
| Backtester | 2h | Triggers backtest if asked (via API) |
| ML State Monitor | 2h | **Reads** params/logs, publishes to Redis (no training) |
| Security Auditor | 6h | FT version check, health, pair locks |

---

## Completed (Iterations 1–4)

### Iteration 1 — Security & Risk
- [x] Fixed `can_short = True` (was blocking all shorts)
- [x] Fixed stoploss bounds, premature exits
- [x] Vectorized sub-regime detection
- [x] Added futures pair guard
- [x] Narrowed CORS from wildcard to localhost

### Iteration 2 — Data Integrity
- [x] Fixed regime model data leakage (removed future-known features)
- [x] Aligned config_backtest.json with production limits
- [x] Fixed broken shell variable syntax in config.json
- [x] Baked ML deps into Dockerfile.agents

### Iteration 3 — Config & API
- [x] Fixed strategy defaults (R1→A51, R2→A52, R3→A52)
- [x] Fixed drawdown normalization guard
- [x] Added server-side API route for ML training
- [x] Added Discord API key authentication
- [x] Cleaned dead R1 long branch

### Iteration 4 — Truthfulness
- [x] Renamed ML optimizer agent → ML State Monitor
- [x] Fixed Discord "training complete" for state refreshes → "state refresh"
- [x] Fixed cmdTrain/cmdBacktest to check API response before confirming
- [x] Added ML state refresh after training completes
- [x] Passed ML_TRAIN_API_KEY to dashboard container
- [x] Added rejection journal to confirm_trade_entry
- [x] Removed dead REGIME_MODEL_PATH, PARAM_MODEL_PATH
- [x] Rewrote README.md (was malformed with literal \n)
- [x] Updated all docs for honest ETH 5m specialist identity

### Iteration 5 — Security & UI
- [x] Replaced exec() with spawn() + argv arrays (downloadData, runBacktests)
- [x] Renamed Chinese agent labels to English across all UI
- [x] Added Operator Diagnostics panel (rejection journal viewer)
- [x] Added /api/diagnostics/rejections endpoint
- [x] Generated agents/package-lock.json for reproducible builds
- [x] Fixed TeamHeader date locale to en-CA + explicit UTC label

### Iteration 6 — Identity & Honesty
- [x] Fixed pair-universe identity: VolumePairList → StaticPairList in config.json
- [x] Fixed ml-train.sh: backtests now use config_backtest.json (StaticPairList)
- [x] Fixed runMarketAnalyst: removed hardcoded ETH pair, uses actual open trades
- [x] Fixed best_params.json R2 direction_bias: "long" → "short" (matches strategy)

---

## Roadmap

### Priority 1 — Operator Observability
- [x] Dashboard panel: latest trade rejection reasons
- [ ] Dashboard panel: entry-tag distribution (what signals fire)
- [ ] Dashboard panel: exit-reason distribution (SL vs ROI vs time)
- [ ] Dashboard panel: live regime from current candle analysis
- [ ] Dashboard panel: session PnL by UTC block
- [ ] Add durable DB (Postgres/TimescaleDB) for trades and decisions

### Priority 2 — Control Plane
- [ ] Move to slash commands in Discord (not prefix-message)
- [ ] Add role-based permissions for train/backtest/pause
- [ ] Operator audit trail for web-triggered actions
- [ ] Full training pipeline: download data → backtest → retrain → publish
- [ ] Explicit training UX: "retrain from existing backtests" vs "full refresh"

### Priority 3 — ML Integrity
- [ ] Wire regime model into live decisions (or remove training code)
- [ ] Rebuild quality model with richer entry-known features
- [ ] Proper walk-forward: refit per slice + forward replay
- [ ] Validate R0/R1/R3 edges before re-enabling

### Priority 4 — Code Quality
- [x] Use `spawn()` with argv arrays instead of `exec()` for commands
- [x] Add `package-lock.json` + `npm ci` for reproducible builds
- [x] Standardize dashboard language (currently mixed Chinese/English)
- [x] Add explicit timezone labels to all timestamps
- [ ] Split coordinator.mjs (1340 lines) into modules
- [ ] Split ml_optimizer.py (2083 lines) into modules

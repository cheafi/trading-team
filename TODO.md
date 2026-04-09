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

## Backtest Results

### 3-Year Backtest (Jan 2023 – Dec 2025, 6 pairs)

| Strategy | Trades | Avg P/L% | Tot P/L USDT | Win% | Max DD | Profit Factor | Sharpe |
|----------|--------|----------|-------------|------|--------|---------------|--------|
| A52Strategy | 27,313 | -0.10 | -2,604 | 46.7% | 26.05% | 0.73 | -68.41 |
| OPTStrategy | 23,629 | -0.10 | -3,026 | 57.5% | 30.55% | 0.75 | -52.17 |
| A51Strategy | 2,356 | -0.10 | -170 | 52.0% | 1.70% | 0.60 | -9.32 |
| A31Strategy | 4,333 | -0.15 | -1,016 | 35.1% | 10.17% | 0.54 | -20.28 |
| AdaptiveMLStrategy | 13 | -0.13 | -0.33 | 38.5% | 0.01% | 0.48 | -0.08 |

**Honest assessment:**
- All 5 strategies are net negative over 3 years — **no edge found yet**.
- AdaptiveMLStrategy's quality gate + anti-pattern filter correctly blocks most bad trades (only 13 entries), but the 13 it allows still lose.
- A52 and OPT generate massive trade volume (23K-27K) but bleed slowly (-0.10% avg).
- A51 is the most capital-preserving (-1.7% DD) but still negative.
- A31 has worst win rate (35.1%) — squeeze breakout doesn't work in ranging regime.
- OPT has best win rate (57.5%) but worst drawdown (30.55%) — wins too small vs losses.
- The meta-strategy (AdaptiveML) successfully protects capital by being extremely selective, but has no positive edge to exploit.

### Short-period Backtest (Jan 1 – Mar 29, 2026)

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

### Iteration 7 — 6-Pair Expansion & Discord UX
- [x] Expanded from ETH-only to 6 pairs (ETH, BTC, SOL, BNB, XRP, DOGE)
- [x] Downloaded 5-year data (2021–2025) for all pairs × 3 timeframes
- [x] Discord bot UX overhaul (color palette, brand helper, shortcuts)

### Iteration 8 — Professional Review Fixes
- [x] Fixed 4 stale GitHub URLs (docs/index.html, README.md)
- [x] Fixed regime labeling leakage: symmetric → causal backward-only window
- [x] Removed dead perf_history code from AdaptiveMLStrategy.py
- [x] Verified rejection journal wiring (14 call sites → disk → API → dashboard)
- [x] 3-year backtest suite: all 5 strategies × 6 pairs (A52/OPT/A51/A31/AdaptiveML)
- [x] Freqtrade container memory bumped 2G→4G (5yr data was OOM-killing backtests)

### Iteration 9 — Second Review: Truthfulness & Security Hardening
- [x] Fixed ml-train.sh: download step now uses config_backtest.json (was config.json)
- [x] Fixed Discord cmdStrategies(): replaced fabricated strategy table with real FT API per-pair data
- [x] Removed hardcoded API secrets from config.json and config_backtest.json (env-override placeholders)
- [x] Cleaned training_log.json: removed 1 placeholder entry with impossible metrics

### Iteration 10 — Governance & Security (Day 1–30 items)
- [x] Enabled GitHub security stack: CodeQL, Dependabot, secret scanning
- [x] Closed auth gap: mutating endpoints require API key or explicit ALLOW_OPEN_AUTH=true
- [x] Added startup env validation (warns on default passwords, missing keys, open auth)
- [x] Fixed docs/index.html meta description: removed "Autonomous AI" / "ML-optimized" inflation
- [x] Fixed agents/SOUL.md: honest identity (6 pairs, R2 short specialist, not autonomous AI)
- [x] Fixed coordinator downloadData(): config.json → config_backtest.json
- [x] Injected ML_TRAIN_API_KEY + ALLOW_OPEN_AUTH into agent-runner container

---

## 90-Day Roadmap

### Phase 1: Truthfulness & Safety (Days 1–30)
- [x] Every surface shows actual live strategy identity
- [x] State refresh cleanly separated from real training
- [x] Rejection journal: strategy → disk → API → dashboard
- [x] CodeQL, secret scanning, Dependabot enabled
- [x] All mutating routes behind auth
- [x] Startup validation for env/config/auth mismatches
- [ ] Decision journal v2: add feature snapshot, model version, risk state per entry
- [ ] CI gate: run `freqtrade lookahead-analysis` on every strategy PR
- [ ] Startup self-test: verify FT API connectivity + config parity before accepting traffic

### Phase 2: Architecture & Reproducibility (Days 31–60)
- [ ] Split coordinator.mjs → ft-client.mjs, job-manager.mjs, notifier.mjs, router.mjs
- [ ] Split ml_optimizer.py → trainer.py, scorer.py, regime.py, registry.py
- [ ] Introduce proper job queue (Bull/BullMQ) + durable DB (Postgres or SQLite)
- [ ] CI pipeline: backtest + lookahead-analysis + dry-run promotion gates
- [ ] Freeze pair universe for research; make universe changes explicit and versioned
- [ ] Canonical research config vs live config with explicit diff

### Phase 3: Intelligence That Deserves the Name (Days 61–90)
- [ ] Model registry: training window, feature hash, OOS metrics, drift status, rollback
- [ ] Rebuild regime/quality models from strictly decision-time features
- [ ] Shadow mode: candidate model makes decisions but cannot trade
- [ ] Trade replay: candle state + features + risk filters + exit cause + PnL attribution
- [ ] Risk cockpit: gross/net exposure, concentration, worst-case loss, drift warnings
- [ ] Public site → clean docs/landing/trust layer; operator console → authenticated app

### Deferred
- [ ] Move to Discord slash commands (not prefix-message)
- [ ] Role-based permissions for train/backtest/pause
- [ ] OpenTelemetry: traces, metrics, logs across all services
- [ ] Wire regime model into live decisions (or remove training code)
- [ ] Proper walk-forward: refit per slice + forward replay
- [ ] Validate R0/R1/R3 edges before re-enabling

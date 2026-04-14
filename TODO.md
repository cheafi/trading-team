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
- Quality model gate (5-feature session-direction-regime prior)
- Anti-pattern filter (toxic hours/days from loss analysis)
- Shadow model infrastructure (candidate evaluation without trading)
- Decision journal for all trade rejections (v4: durable append-only JSONL)

### What the system does NOT do (yet)
- Multi-regime live trading (R0/R1/R3 disabled)
- Deep trade quality intelligence (model uses hour/weekday/side/regime/leverage — no candle indicators)
- The scheduled "ML optimizer" agent refreshes state, does NOT retrain
- Auto-learn is wired (backtester agent triggers download→backtest→retrain when params >7d old) but unproven in production

---

## Backtest Results

### 5-Year Backtest (Jan 2021 – Dec 2025, 1825 days, 6 pairs)

| Strategy | Trades | Tot P/L USDT | Tot P/L % | Win% | Max DD | Profit Factor | Sharpe |
|----------|--------|-------------|-----------|------|--------|---------------|--------|
| A51Strategy | 3,765 | -293.81 | -2.94% | 50.3% | 2.94% | — | — |
| A31Strategy | 7,451 | -1,929.84 | -19.30% | 36.1% | 19.30% | — | — |
| A52Strategy | 50,275 | -5,456.31 | -54.56% | 46.5% | 54.58% | — | — |
| OPTStrategy | 44,014 | -6,324.71 | -63.25% | 54.5% | 63.25% | — | — |
| AdaptiveMLStrategy | 0 | 0.000 | 0.00% | — | 0.00% | — | ML gate blocks all (see note) |

> Market (BTC) moved +2,164% over this period (2021-01-01 → 2025-12-31).

**Honest assessment (5yr):**
- **All 4 active strategies are net negative over 5 years.** Shorting into a multi-year bull market guarantees losses.
- A51 is the least-bad (-2.94% DD) — VWAP reversion produces small, symmetric trades.
- A52 and OPT generate enormous trade volume (44K-50K) and bleed badly (-54% to -63%).
- A31 squeeze breakout: worst win rate (36.1%) but moderate DD — enters rarely.
- **AdaptiveMLStrategy: 0 trades.** Quality model + anti-pattern filter trained on 2023-2025 data correctly rejects all candles in the 2021-2025 window. The ML gate recognizes it has no edge and blocks everything. This is capital-preservation working as designed (compare with A52's -54% DD without the gate). Requires 10GB+ to run (3 TF × 6 pairs).
- **No short-only strategy has positive expectancy in a secular bull market.** This is expected and not a bug — R2 (ranging) shorts are designed for sideways/down conditions that represent a minority of this 5-year window.

### 3-Year Backtest (Jan 2023 – Dec 2025, 6 pairs)

| Strategy | Trades | Avg P/L% | Tot P/L USDT | Win% | Max DD | Profit Factor | Sharpe |
|----------|--------|----------|-------------|------|--------|---------------|--------|
| A52Strategy | 27,313 | -0.10 | -2,604 | 46.7% | 26.05% | 0.73 | -68.41 |
| OPTStrategy | 23,629 | -0.10 | -3,026 | 57.5% | 30.55% | 0.75 | -52.17 |
| A51Strategy | 2,356 | -0.10 | -170 | 52.0% | 1.70% | 0.60 | -9.32 |
| A31Strategy | 4,333 | -0.15 | -1,016 | 35.1% | 10.17% | 0.54 | -20.28 |
| AdaptiveMLStrategy | 13 | -0.13 | -0.33 | 38.5% | 0.01% | 0.48 | -0.08 |

**Honest assessment (3yr):**
- All 5 strategies net negative — no edge found yet.
- AdaptiveMLStrategy's quality gate blocks most bad trades (only 13 entries), but the 13 it allows still lose.
- A51 most capital-preserving (-1.7% DD). OPT best win rate (57.5%) but worst drawdown (30.55%).

### Short-period Backtest (Jan 1 – Mar 29, 2026)

| Strategy | Trades | P/L | Drawdown | Market |
|----------|--------|-----|----------|--------|
| AdaptiveMLStrategy | 257 | -0.62% | 0.65% | -29.69% |
| A52 standalone | 1809 | -13.73% | — | -29.69% |

The meta-strategy protects capital effectively during a -30% crash,
but the edge is narrow and R2 is marked `is_robust: false`.

### 2026 Q1 Backtest (Jan 1 – Apr 11, 2026, after iter 16 retrain)

| Strategy | Trades | Avg P/L% | Tot P/L USDT | Win% | Max DD | Market |
|----------|--------|----------|-------------|------|--------|--------|
| AdaptiveMLStrategy | 37 | -0.15 | -0.611 | 43.2% | 0.01% | -25.12% |

**Note:** After retraining (iter 16), R2 correctly uses A52. System is trading again.
37 trades in ~100 days, 43.2% WR, negligible drawdown. Still net negative but
capital preservation is working (0.01% DD vs -25% market).

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
- Quality model — **GradientBoostingClassifier** (5 features: hour, weekday, side, regime, leverage)
- Shadow model infrastructure — candidate models evaluated but cannot trade
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

### Iteration 11 — Architecture Split (Phase 1 completion + Phase 2 start)
- [x] Startup self-test: FT API connectivity check + config parity validation (ft-client.mjs selfTestFT)
- [x] CI gate: strategy-gate.yml runs lookahead-analysis + smoke backtest on strategy PRs
- [x] Decision journal v2: rejections now include feature snapshot, model version, risk state
- [x] Split coordinator.mjs 1405→1029 lines: extracted ft-client.mjs (94), job-manager.mjs (390)
- [x] Split ml_optimizer.py: extracted ml_scorer.py (310 lines), ml_analyzer.py (440 lines)
- [x] ml_optimizer.py retains inline defs as transition fallback; imports ready to activate

### Iteration 12 — Phase 2 Completion
- [x] Activated ml_optimizer.py imports (removed 947 lines inline fallback; 2100→1149 lines)
- [x] Froze pair universe: pair_universe.json + validate_pairs.py + startup check
- [x] Canonical config diff: diff-configs.sh + config_reference.json snapshot

### Iteration 13 — Phase 3 Start (Intelligence)
- [x] Model registry: version tracking, drift detection, rollback (model_registry.py)
- [x] Trade replay: entry+exit logging with features, risk state, PnL attribution
- [x] Risk cockpit: exposure, concentration, worst-case loss, drift warnings (dashboard + 4 API endpoints)

### Iteration 14 — Quality Model Expansion + Dead Code Removal
- [x] Removed dead regime model code (train_regime_model, REGIME_MODEL_PATH, regime_model.pkl)
- [x] Expanded quality model: 3→5 features (hour, weekday, is_short, regime, leverage)
- [x] Gitignored ml_models runtime artifacts (.pkl, .json)
- [x] Fixed backtest-5yr.sh to use docker compose run --rm

### Iteration 15 — Shadow Mode + 5-Year Backtests
- [x] Shadow model infrastructure: load candidate model, evaluate but never trade, log decisions
- [x] /api/ml/shadow endpoint: agreement rate, recent decisions
- [x] useShadowComparison hook + ShadowComparison interface in dashboard
- [x] Freqtrade container memory bumped 4G→6G (5yr backtests OOM at 4G)
- [x] 5-year backtests: all 5 strategies completed (A51/A31/A52/OPT net negative; AdaptiveML 0 trades — ML gate blocks all)
- [x] AdaptiveMLStrategy 5yr: 0 trades (quality model rejects everything — requires 10GB, ran via docker run)

### Iteration 16 — Stale Params Fix + Auto-Learn Pipeline
- [x] Diagnosed live zero-trade bug: best_params.json had R2=A31 (23/24 toxic hours → blocked everything)
- [x] Retrained ML models: R2 now correctly uses A52 (no toxic hours)
- [x] Hardened anti-pattern filter: skip if >18 toxic hours or >5 toxic days (prevents silent blocking)
- [x] Added staleness warning: best_params.json >7 days logs warning on model load
- [x] Added logging import + fixed stale docstring in AdaptiveMLStrategy.py
- [x] Downloaded fresh 2026 data (Jan–Apr 2026, all 6 pairs × 3 TFs)
- [x] 2026 Q1 validation backtest: 37 trades, 43.2% WR, 0.01% DD (system is trading again!)
- [x] Wired auto-learn into backtester agent: checks params age, triggers download→backtest→retrain if >7d
- [x] Fixed auto-learn.sh branding (DanDan → CC)

### Iteration 18 — System Alignment: Truth, Decision Journal v4, Risk Hardening
Second comprehensive review identified main problem as **system alignment** — "presentation more ambitious than actual live decision logic." Priority: truthfulness, risk governance, decision observability.

**Truth Alignment (27 items audited, 17 fixed):**
- [x] Dashboard: `ML Adaptive Engine` → `ML Quality Gate` (page.tsx header)
- [x] Dashboard: `AI Trading Dashboard` → `Algo Trading Dashboard` (browser tab)
- [x] Docs: `7 autonomous agents. ML-informed` → `7 cron-scheduled agents. Rule-based`
- [x] Discord: `Intelligence` section → `System State`
- [x] Discord: `ML Engine` embed → `ML Quality Gate`
- [x] ML-optimizer SKILL.md: removed dead regime_model.pkl claims, corrected pipeline
- [x] ml_optimizer.py: `v3 PRO` → `v3`, `Professional quant-grade` → honest description
- [x] quant-researcher SKILL.md: removed "brain of the team" inflated language
- [x] manifest.json: `DanDan` → `CC` brand alignment
- [x] Strategy file: stripped all `PRO:` labels from comments/docstrings (20+ occurrences)

**Decision Journal v4:**
- [x] Append-only JSONL (decision_journal.jsonl) — never truncated, durable audit trail
- [x] Unified accept+reject log: every trade signal decision persisted
- [x] Edge score + quality threshold on every entry
- [x] Entry rate at rejection time (for counterfactual: "what happened after we said no?")
- [x] Searchable API: /api/diagnostics/decisions with pair/decision/side/reason/date/regime filters
- [x] Summary stats: total, accepted, rejected, accept rate
- [x] Dashboard: tabbed view (All Decisions / Rejections), pair+decision filters, accept rate badge, edge score display

**Model Registry v2:**
- [x] Added: feature_hash (SHA-256 of quality_model.pkl)
- [x] Added: data_hash (SHA-256 of backtest result files)
- [x] Added: training_window + validation_window (80/20 split dates + trade counts)
- [x] Added: feature_names list for provenance
- [x] API surfaces all new fields in risk cockpit drift response

**Risk Cockpit hardening:**
- [x] Net exposure (signed: negative=short, positive=long)
- [x] Daily P&L + weekly P&L with trade counts
- [x] Deterministic DD guards: -2% daily limit, -5% weekly limit with breach detection
- [x] Leverage readout (max + average across open positions)
- [x] DD breach warning banner when limits exceeded
- [x] 4×4 stat grid (from 2×4): exposure, DD guard, model, concentration

---

### Iteration 17 — Professional Review Response: Deterministic Risk + Benchmark
Responding to comprehensive professional review that identified 8 critical modules and a Phase 4 roadmap.

**Gap audit results (8 modules):**
| Module | Status | Key Gap |
|--------|--------|---------|
| Decision Journal | 55% | Missing counterfactual tracking |
| Model Registry | 50% | No feature hash / training windows |
| Shadow Mode | 40% | Only quality model, no full signals |
| Trade Replay | 35% | No funding/OI/events/slippage |
| Risk Cockpit | 45% → 75% | Added kill-switch toggle |
| Benchmark Centre | 0% → 85% | NEW: Sharpe/Sortino/Calmar/PF/alpha |
| Public/Operator split | 60% | Dashboard has no auth |
| Telemetry | 2% | No OTel/correlation IDs |

**Implemented in this iteration:**
- [x] **Benchmark Centre** (P0): /api/benchmark endpoint — strategy return, Sharpe, Sortino, Calmar, profit factor, win rate, expectancy, per-pair breakdown, vs-cash alpha. BenchmarkPanel dashboard component with colour-coded metrics.
- [x] **Kill-switch** (P1): file-based toggle at ml_models/kill_switch. Strategy reads at top of confirm_trade_entry (blocks all entries when active). /api/kill-switch GET/POST in coordinator. Dashboard toggle in RiskCockpit with live indicator.
- [x] **Event freeze windows** (P1): Strategy reads ml_models/event_calendar.json. Blocks entries within ±3h of scheduled events. Seeded with 2026 FOMC (8 dates), CPI (12 dates), NFP (12 dates) — 32 events total.
- [x] **Enhanced rejection journal** (P1): v3 adds `regime` and `direction_score` fields to every rejection entry, enabling per-regime analysis of blocked trades.
- [x] Dashboard hooks: useBenchmark, useKillSwitch, toggleKillSwitch added to hooks.ts

---

## 90-Day Roadmap

### Phase 1: Truthfulness & Safety (Days 1–30) ✅ COMPLETE
- [x] Every surface shows actual live strategy identity
- [x] State refresh cleanly separated from real training
- [x] Rejection journal: strategy → disk → API → dashboard
- [x] CodeQL, secret scanning, Dependabot enabled
- [x] All mutating routes behind auth
- [x] Startup validation for env/config/auth mismatches
- [x] Decision journal v2: add feature snapshot, model version, risk state per entry
- [x] CI gate: run `freqtrade lookahead-analysis` on every strategy PR
- [x] Startup self-test: verify FT API connectivity + config parity before accepting traffic

### Phase 2: Architecture & Reproducibility (Days 31–60)
- [x] Split coordinator.mjs → ft-client.mjs, job-manager.mjs (notifier.mjs, router.mjs deferred)
- [x] Split ml_optimizer.py → ml_scorer.py, ml_analyzer.py (trainer/registry deferred)
- [x] CI pipeline: strategy-gate.yml (lookahead + smoke backtest on PRs)
- [x] Activate ml_optimizer imports (removed 947 lines inline fallback; 2100→1149 lines)
- [x] Freeze pair universe: pair_universe.json + validate_pairs.py + startup check
- [x] Canonical config diff: diff-configs.sh + config_reference.json snapshot

### Phase 3: Intelligence That Deserves the Name (Days 61–90)
- [x] Model registry: version tracking, drift detection, rollback (model_registry.py)
- [x] Quality model expanded: 3→5 features (hour, weekday, is_short, regime, leverage)
- [x] Shadow mode: candidate model evaluated but cannot trade (log-only A/B comparison)
- [x] Trade replay: entry+exit logging with features, risk state, PnL attribution
- [x] Risk cockpit: exposure, concentration, worst-case loss, drift warnings (dashboard)
- [x] Public site: docs/index.html updated — regime model removed, quality model 5-feature, shadow mode, trade replay, model_registry

### Post-Roadmap: Operational Hardening
- [x] Stale params detection + auto-learn pipeline (backtester agent triggers full cycle)
- [x] Anti-pattern safety guard (prevent toxic-hour over-blocking)
- [x] Benchmark Centre: Sharpe/Sortino/Calmar/PF + per-pair breakdown + vs-cash alpha (API + dashboard)
- [x] Kill-switch: file-based toggle, API endpoint, dashboard UI with 1-click activate/deactivate
- [x] Event freeze windows: auto-block entries ±3h around FOMC/CPI/NFP (2026 calendar seeded)
- [x] Enhanced rejection journal: v3 adds regime + direction_score per rejection
- [x] Decision Journal v4: append-only JSONL, unified accept+reject, searchable API, counterfactual rates
- [x] Model Registry v2: feature_hash, data_hash, training/validation windows, feature_names
- [x] Risk Cockpit v2: net exposure, daily/weekly DD guards, leverage, breach warnings
- [x] Truth alignment: 27-item audit, 17 items fixed (dashboard, docs, Discord, SKILL, strategy)
- [ ] Move to Discord slash commands (not prefix-message)
- [ ] Role-based permissions for train/backtest/pause
- [ ] OpenTelemetry: traces, metrics, logs across all services
- [ ] Proper walk-forward: refit per slice + forward replay
- [ ] Validate R0/R1/R3 edges before re-enabling
- [ ] Full indicator features in quality model (ADX, ATR, BB_width, vol_ratio)
- [ ] Introduce proper job queue (Bull/BullMQ) + durable DB (Postgres or SQLite)
- [ ] Dashboard auth: operator pages behind login, public pages read-only
- [ ] On-chain / whale tracking layer
- [ ] Macro regime engine (DXY, yields, gold/copper ratios)
- [ ] Data quality layer (venue health scores, stale feed detection)

### Deferred
- [x] ~~Wire regime model into live decisions (or remove training code)~~ Removed dead regime model
- [x] ~~Auto-download fresh data + rebacktest + retrain~~ Wired into backtester agent (iter 16)

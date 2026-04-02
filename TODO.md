# Cheafi — Multi-Agent Algo Trading Platform

## Current Status (2026-04-01)

### System Health
- ✅ All 4 Docker containers running (freqtrade, redis, dashboard, agent-runner)
- ✅ Freqtrade v2026.2, futures/isolated mode, Binance
- ✅ Discord bot connected (`Crypto Algo Team#3543`, server: `crypto-algo-team`)
- ✅ Dashboard live on port 3000

### Backtest Results (Jan 1 – Mar 29, 2026)
| Strategy | Trades | P/L | Drawdown | Market |
|----------|--------|-----|----------|--------|
| **AdaptiveMLStrategy** | 257 | **-0.62%** | 0.65% | -29.69% |
| A52 standalone | 1809 | -13.73% | — | -29.69% |

The AdaptiveML meta-strategy **outperforms A52 by 22×** and protects capital
effectively during a -30% market crash.

---

## Recent Improvements (v4)

### 14 Bug Fixes
1. `can_short = True` — was False, blocking all short trades
2. Stoploss min/max inversion — proper bounds applied
3. Premature exits in A52/A51/OPT — changed OR to AND with confirmation
4. `_merge_informative` — fixed broken merge with `pd.merge_asof`
5. Sub-regime detection — vectorized (was O(n) row-by-row loop)
6. Symmetric `confirm_trade_entry` for all sub-strategies
7. Config switched from spot to futures mode with `:USDT` pair suffixes

### Intelligence Upgrades
- **Quality model gate** — AI-driven trade filtering with backtest guard
- **Regime transition filter** — reduces entry during regime shifts
- **Anti-pattern detection** — learns toxic hours/days from losing trades
- **Adaptive scoring** — 60% recent + 40% overall recency bias
- **Volatility spike exit** — auto-exits when ATR spikes during regime change
- **Progressive trailing stop** — locks in 60-75% of gains based on profit level
- **Per-candle A52 fallback** — fills gaps when primary strategy doesn't fire
- **1h trend filter for fallback longs** — prevents catching falling knives
- **Regime-adaptive thresholds** — different dir_thresh / vol_mult per regime
- **Wider R3 stoploss** — 1.2% for volatile regime (was 0.6%)

### Entry Condition Tuning (Data-Driven)
| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| dir_thresh (ranging) | 0.50 | 0.20 | Mean dir_score in R2 ≈ 0.0 |
| dir_thresh (trending) | 0.50 | 0.35 | Mean dir_score in R0 ≈ 0.4 |
| vol_mult (ranging) | 1.30 | 1.00 | Low vol normal in ranging |
| vol_mult (trending) | 1.30 | 1.20 | Want confirmation |
| RSI band (A51) | 40-60 | 35-65 | Was filtering 75% of candles |
| Volume (A31) | 1.5× | 0.8× | Squeeze_fire already rare |
| R3 fallback | enabled | **disabled** | Caused 71% of losses |

---

## Architecture

### Regime System
| ID | Regime | Strategy | Fallback |
|----|--------|----------|----------|
| R0 | TRENDING_UP | A31 (squeeze) | A52 |
| R1 | TRENDING_DOWN | A51 (VWAP scalp) | A52 |
| R2 | RANGING | A51 (VWAP scalp) | A52 |
| R3 | VOLATILE | A31 (squeeze) | None |

### Sub-Strategies
- **A52**: Multi-TF momentum + mean-reversion (110 trades/month standalone)
- **A51**: VWAP + order block scalping (c=0.35)
- **A31**: Volatility squeeze breakout (c=0.80, rare signals)
- **OPT**: Ichimoku + SuperTrend trend follower (c=0.65)

### ML Pipeline (`ml_optimizer.py`)
- Regime model (RandomForest)
- Quality model (XGBoost) for trade filtering
- Walk-forward validation
- Monte Carlo simulation
- Anti-pattern detection (toxic hours/days)
- Adaptive scoring with recency bias
- Kelly criterion position sizing

---

## Roadmap

### Short Term
- [ ] Hyperopt for per-regime ROI/SL optimization
- [ ] Add more pairs (DOGE, ADA, AVAX) for diversification
- [ ] Retrain ML models on latest data
- [ ] Test in bull market conditions

### Medium Term
- [ ] Live paper trading validation (1 week min)
- [ ] Position sizing optimization (Kelly fraction)
- [ ] Cross-pair correlation filter
- [ ] Dashboard: show regime, entry tags, live P&L

### Long Term
- [ ] Real money deployment with progressive sizing
- [ ] Multi-exchange support
- [ ] Automated model retraining pipeline
- [ ] Alert system for anomalous behavior

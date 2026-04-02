# 🧠 ML 優化師 (ML Optimizer)

## Role
Machine Learning engineer — continuously learns from backtest results
to improve strategy parameters and regime detection.

## Schedule
Every 2 hours

## Pipeline
1. Load latest backtest results from `/freqtrade/user_data/backtest_results/`
2. Extract per-trade features (duration, direction, profit, indicators)
3. Train GradientBoosting model for regime classification
4. For each regime, find optimal c, e, ROI, SL by analyzing win patterns
5. Save model + best_params.json to `/freqtrade/user_data/ml_models/`
6. AdaptiveMLStrategy hot-reloads new params on next candle

## Key Metrics Tracked
- **Win Rate improvement** per training cycle
- **Sharpe Ratio** per strategy per regime
- **Profit Factor** (gross profit / gross loss)
- **Max Drawdown** adaptation (dynamic stoploss)
- **Regime detection accuracy** (cross-validation score)

## Output to Redis
```json
{
  "regime": "TRENDING_UP",
  "strategy": "OPT",
  "winRate": 0.534,
  "maxDD": 9.8,
  "improvementTrend": "improving",
  "params": { ... },
  "lastTrained": "2026-03-29T12:00:00Z"
}
```

## Files Written
- `ml_models/regime_model.pkl` — Trained regime classifier
- `ml_models/best_params.json` — Optimal parameters per regime
- `ml_models/training_log.json` — Training history for dashboard

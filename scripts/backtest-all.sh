#!/usr/bin/env bash
# ──────────────────────────────────────────────────
# Run Freqtrade backtest for all strategies
# ──────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

STRATEGIES=("A52Strategy" "OPTStrategy" "A51Strategy" "A31Strategy" "AdaptiveMLStrategy")
TIMERANGE="${1:-20240101-20241231}"

echo "📊 CC Trading Team — Backtest Suite"
echo "─────────────────────────────────────────"
echo "Timerange: $TIMERANGE"
echo ""

# Download data first
echo "📥 Downloading ETH/USDT 5m + 15m + 1h data..."
docker compose run --rm freqtrade download-data \
    --config /freqtrade/config/config_backtest.json \
    --pairs ETH/USDT:USDT \
    --timeframes 5m 15m 1h \
    --timerange "$TIMERANGE"

echo ""

for STRATEGY in "${STRATEGIES[@]}"; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🏃 Backtesting: $STRATEGY"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    docker compose run --rm freqtrade backtesting \
        --config /freqtrade/config/config_backtest.json \
        --strategy "$STRATEGY" \
        --strategy-path /freqtrade/user_data/strategies \
        --timerange "$TIMERANGE" \
        --timeframe 5m \
        --enable-protections \
        --export trades \
        || echo "⚠️  $STRATEGY backtest failed"
    
    echo ""
done

echo "✅ All backtests complete!"
echo "📁 Results in: ./freqtrade/user_data/backtest_results/"

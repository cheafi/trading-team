#!/usr/bin/env bash
# Run all strategy backtests and save summary
set -euo pipefail
cd "$(dirname "$0")/.."

TIMERANGE="20240101-20260329"
STRATEGIES=("OPTStrategy" "A51Strategy" "A31Strategy" "AdaptiveMLStrategy")
SUMMARY_FILE="freqtrade/user_data/backtest_results/backtest_summary.txt"

echo "📊 Cheafi — Running all backtests (${#STRATEGIES[@]} strategies)" > "$SUMMARY_FILE"
echo "Timerange: $TIMERANGE" >> "$SUMMARY_FILE"
echo "Started: $(date)" >> "$SUMMARY_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> "$SUMMARY_FILE"

for STRATEGY in "${STRATEGIES[@]}"; do
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🏃 Backtesting: $STRATEGY"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    echo "" >> "$SUMMARY_FILE"
    echo "=== $STRATEGY ===" >> "$SUMMARY_FILE"

    OUTPUT=$(docker compose run --rm freqtrade backtesting \
        --config /freqtrade/config/config.json \
        --strategy "$STRATEGY" \
        --strategy-path /freqtrade/user_data/strategies \
        --timerange "$TIMERANGE" \
        --timeframe 5m \
        --enable-protections \
        --export trades 2>&1) || true

    # Extract key metrics
    echo "$OUTPUT" | grep -E "(TOTAL|Total|Sharpe|Sortino|Calmar|Profit factor|Max.*underwater|Drawdown duration|Win)" | head -12 | tee -a "$SUMMARY_FILE"

    echo "✅ $STRATEGY complete"
done

echo "" >> "$SUMMARY_FILE"
echo "Completed: $(date)" >> "$SUMMARY_FILE"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All backtests complete!"
echo "📁 Summary: $SUMMARY_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

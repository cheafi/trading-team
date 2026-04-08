#!/usr/bin/env bash
# ──────────────────────────────────────────────────
# 5-Year Backtest Suite — CC Trading Team
# Runs all strategies against 2021-2026 data
# ──────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

STRATEGIES=("A52Strategy" "OPTStrategy" "A51Strategy" "A31Strategy" "AdaptiveMLStrategy")
TIMERANGE="20210101-20260101"
RESULTS_DIR="freqtrade/user_data/backtest_results"

echo "📊 CC Trading Team — 5-Year Backtest Suite"
echo "─────────────────────────────────────────"
echo "Timerange: $TIMERANGE (1825 days)"
echo "Pairs: ETH, BTC, SOL, BNB, XRP, DOGE"
echo ""

for STRATEGY in "${STRATEGIES[@]}"; do
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	echo "🏃 Backtesting: $STRATEGY"
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

	docker compose run --rm -T freqtrade backtesting \
		--config /freqtrade/config/config_backtest.json \
		--strategy "$STRATEGY" \
		--strategy-path /freqtrade/user_data/strategies \
		--timerange "$TIMERANGE" \
		--timeframe 5m \
		--enable-protections \
		--export trades ||
		echo "⚠️  $STRATEGY backtest failed"

	echo ""
done

echo "✅ All 5-year backtests complete!"
echo "📁 Results in: ./$RESULTS_DIR/"

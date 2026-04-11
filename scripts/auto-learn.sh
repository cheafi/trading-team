#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 🔄 Continuous Learning Daemon
# ──────────────────────────────────────────────────────────
# Runs the ML training pipeline on a loop:
#   - Every N hours, download fresh data, re-backtest, retrain
#   - Automatically deploys updated parameters
#
# Usage:
#   ./scripts/auto-learn.sh           # default: every 6 hours
#   ./scripts/auto-learn.sh 2         # every 2 hours
#   nohup ./scripts/auto-learn.sh &   # run in background
# ──────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

INTERVAL_HOURS="${1:-6}"
INTERVAL_SECS=$((INTERVAL_HOURS * 3600))
CYCLE=0

echo "🔄 CC Continuous Learning Daemon"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⏰ Retrain interval: every ${INTERVAL_HOURS}h"
echo "📊 Strategy: AdaptiveMLStrategy"
echo ""

while true; do
    CYCLE=$((CYCLE + 1))
    echo ""
    echo "━━━ Cycle #${CYCLE} — $(date '+%Y-%m-%d %H:%M:%S') ━━━"

    # Calculate timerange: last 3 months rolling window
    START=$(date -v-3m +%Y%m%d 2>/dev/null || date -d '3 months ago' +%Y%m%d)
    END=$(date +%Y%m%d)
    TIMERANGE="${START}-${END}"

    echo "📅 Training window: $TIMERANGE"

    # Run the ML pipeline
    ./scripts/ml-train.sh "$TIMERANGE" 2>&1 | while IFS= read -r line; do
        echo "  $line"
    done

    # Log the cycle
    echo "{\"cycle\": $CYCLE, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"timerange\": \"$TIMERANGE\"}" \
        >> freqtrade/user_data/ml_models/auto_learn_log.jsonl

    echo ""
    echo "✅ Cycle #${CYCLE} complete. Next run in ${INTERVAL_HOURS}h..."
    echo "   (Press Ctrl+C to stop)"

    sleep "$INTERVAL_SECS"
done

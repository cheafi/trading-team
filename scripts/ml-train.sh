#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 🧠 ML Training Pipeline — Backtest → Learn → Deploy
# ──────────────────────────────────────────────────────────
# This script runs the full optimization cycle:
#   1. Download latest data
#   2. Run backtests for ALL strategies
#   3. Run ML optimizer to learn from results
#   4. Deploy updated params (AdaptiveMLStrategy hot-reloads)
#
# Usage:
#   ./scripts/ml-train.sh                    # full cycle, last 6 months
#   ./scripts/ml-train.sh 20240601-20250101  # custom range
#   ./scripts/ml-train.sh --skip-backtest    # relearn from existing results
# ──────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

TIMERANGE=""
SKIP_BACKTEST=false

# Parse args
for arg in "$@"; do
    case "$arg" in
        --skip-backtest) SKIP_BACKTEST=true ;;
        *) TIMERANGE="$arg" ;;
    esac
done

# Default: last 6 months
if [ -z "$TIMERANGE" ]; then
    START=$(date -v-6m +%Y%m%d 2>/dev/null || date -d '6 months ago' +%Y%m%d)
    END=$(date +%Y%m%d)
    TIMERANGE="${START}-${END}"
fi

STRATEGIES=("A52Strategy" "OPTStrategy" "A51Strategy" "A31Strategy" "AdaptiveMLStrategy")

echo "🧠 CC ML Training Pipeline"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📅 Time range: $TIMERANGE"
echo "📊 Strategies: ${STRATEGIES[*]}"
echo ""

# ─── Step 1: Download data ─────────────────────────────────────
echo "📥 Step 1/4: Downloading market data..."
docker compose run --rm freqtrade download-data \
    --config /freqtrade/config/config.json \
    --pairs ETH/USDT:USDT \
    --timeframes 5m 15m 1h \
    --timerange "$TIMERANGE" \
    2>&1 | tail -5
echo "✅ Data downloaded"
echo ""

# ─── Step 2: Run backtests ─────────────────────────────────────
if [ "$SKIP_BACKTEST" = false ]; then
    echo "📊 Step 2/4: Running backtests..."

    for STRATEGY in "${STRATEGIES[@]}"; do
        echo "  🏃 $STRATEGY..."
        docker compose run --rm freqtrade backtesting \
            --config /freqtrade/config/config_backtest.json \
            --strategy "$STRATEGY" \
            --strategy-path /freqtrade/user_data/strategies \
            --timerange "$TIMERANGE" \
            --timeframe 5m \
            --enable-protections \
            --export trades \
            2>&1 | grep -E "(BACKTESTING|Total|Profit|Win|Draw|Loss|Max)" | head -8 \
            || echo "  ⚠️  $STRATEGY backtest failed"
        echo ""
    done
    echo "✅ Backtests complete"
else
    echo "⏩ Step 2/4: Skipping backtests (--skip-backtest)"
fi
echo ""

# ─── Step 3: Run ML optimizer ──────────────────────────────────
echo "🧠 Step 3/4: Training ML models..."

# Create ml_models directory
mkdir -p freqtrade/user_data/ml_models

docker compose run --rm --entrypoint /bin/bash \
    -e BACKTEST_DIR=/freqtrade/user_data/backtest_results \
    -e MODEL_DIR=/freqtrade/user_data/ml_models \
    freqtrade \
    -lc "pip install -q scikit-learn 2>/dev/null; \
        python /freqtrade/user_data/strategies/ml_optimizer.py --retrain" \
    2>&1 | tail -30

echo "✅ ML training complete"
echo ""

# ─── Step 4: Deploy (hot-reload) ──────────────────────────────
echo "🚀 Step 4/4: Deploying updated models..."

# The AdaptiveMLStrategy auto-reloads from disk,
# but we can force a strategy reload via Freqtrade API
curl -sf -X POST \
    -u "${FREQTRADE_USER:-freqtrader}:${FREQTRADE_PASS:-SuperSecure123}" \
    "http://localhost:${FREQTRADE_API_PORT:-8080}/api/v1/reload_config" \
    2>/dev/null && echo "  ✅ Freqtrade config reloaded" \
    || echo "  ℹ️  Freqtrade not running (models will load on next start)"

echo ""

# ─── Summary ───────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ML Pipeline Complete!"
echo ""

if [ -f "freqtrade/user_data/ml_models/best_params.json" ]; then
    echo "📋 Optimized Parameters:"
    cat freqtrade/user_data/ml_models/best_params.json | python3 -m json.tool 2>/dev/null \
        || cat freqtrade/user_data/ml_models/best_params.json
    echo ""
fi

echo "🔄 AdaptiveMLStrategy will auto-load updated models."
echo "📊 View results: http://localhost:3000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

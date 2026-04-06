#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# 🧠 ML Training Pipeline — Container-Safe Version
# ──────────────────────────────────────────────────────────
# Runs INSIDE the agent-runner container (no Docker CLI).
# Executes ml_optimizer.py directly against shared volumes.
#
# Pre-requisites (met by Dockerfile.agents):
#   - python3, pip3
#   - /freqtrade/user_data mounted (shared with freqtrade)
#
# Usage:
#   /app/scripts/ml-train-container.sh              # full run
#   /app/scripts/ml-train-container.sh --retrain    # retrain only
# ──────────────────────────────────────────────────────────
set -euo pipefail

# Force unbuffered output for real-time log streaming
export PYTHONUNBUFFERED=1

OPTIMIZER="/freqtrade/user_data/strategies/ml_optimizer.py"
BACKTEST_DIR="/freqtrade/user_data/backtest_results"
MODEL_DIR="/freqtrade/user_data/ml_models"
FT_API="${FREQTRADE_API:-http://freqtrade:8080}"
FT_USER="${FREQTRADE_API_USER:-freqtrader}"
FT_PASS="${FREQTRADE_API_PASSWORD:-SuperSecure123}"

echo "🧠 CC ML Training Pipeline (container mode)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📂 Optimizer : $OPTIMIZER"
echo "📂 Backtests : $BACKTEST_DIR"
echo "📂 Models    : $MODEL_DIR"
echo ""

# ─── Step 1: Verify prerequisites ─────────────────────────
echo "🔍 Step 1/4: Checking prerequisites..."

if [ ! -f "$OPTIMIZER" ]; then
    echo "❌ ml_optimizer.py not found at $OPTIMIZER"
    exit 1
fi

# Count backtest result files
BT_COUNT=$(find "$BACKTEST_DIR" -name 'backtest-result-*.json' -o -name 'backtest-result-*.zip' 2>/dev/null | wc -l)
echo "  📊 Found $BT_COUNT backtest result files"

if [ "$BT_COUNT" -eq 0 ]; then
    echo "⚠️  No backtest results found. Run backtests first."
    echo "  Hint: POST /api/backtest/run or use scripts/backtest-all.sh"
    exit 1
fi

mkdir -p "$MODEL_DIR"
echo "✅ Prerequisites OK"
echo ""

# ─── Step 2: Verify Python deps (baked into Docker image) ──
echo "📦 Step 2/4: Checking Python dependencies..."
python3 -c "import sklearn; import numpy" 2>/dev/null || {
    echo "❌ scikit-learn or numpy not found."
    echo "  These should be baked into Dockerfile.agents."
    echo "  Rebuild: docker compose build agent-runner"
    exit 1
}
echo "✅ Python deps ready"
echo ""

# ─── Step 3: Run ML Optimizer ─────────────────────────────
echo "🧠 Step 3/4: Training ML models..."
echo ""

export BACKTEST_DIR
export MODEL_DIR

python3 "$OPTIMIZER" --retrain
RETCODE=$?

if [ $RETCODE -ne 0 ]; then
    echo "❌ ML optimizer exited with code $RETCODE"
    exit $RETCODE
fi

echo ""
echo "✅ ML training complete"
echo ""

# ─── Step 4: Notify Freqtrade to hot-reload ───────────────
echo "🚀 Step 4/4: Requesting Freqtrade config reload..."

HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
    -u "${FT_USER}:${FT_PASS}" \
    "${FT_API}/api/v1/reload_config" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ Freqtrade config reloaded (models will activate on next candle)"
else
    echo "  ℹ️  Freqtrade reload returned HTTP $HTTP_CODE (models will load on next restart)"
fi
echo ""

# ─── Summary ──────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ML Pipeline Complete!"

if [ -f "$MODEL_DIR/best_params.json" ]; then
    echo ""
    echo "📋 Updated params summary:"
    python3 -c "
import json, sys
try:
    p = json.load(open('$MODEL_DIR/best_params.json'))
    names = {0:'TREND_UP', 1:'TREND_DOWN', 2:'RANGING', 3:'VOLATILE'}
    for rid, params in sorted(p.items()):
        rn = names.get(int(rid), f'R{rid}')
        wr = params.get('win_rate', 0)
        st = params.get('strategy', '?')
        c = params.get('c', 0)
        k = params.get('kelly_fraction', 0)
        print(f'  {rn:<12} -> {st:<5}  c={c:.2f}  WR={wr:.1%}  kelly={k:.2%}')
except Exception as e:
    print(f'  (could not parse: {e})')
" 2>/dev/null || true
fi

echo ""
echo "🔄 AdaptiveMLStrategy will hot-reload updated models."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

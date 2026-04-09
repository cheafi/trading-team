#!/usr/bin/env bash
# ============================================================
# CC Backtest Suite — runs all strategies inside freqtrade container
# ============================================================
# Usage (from host):
#   docker exec -d freqtrade bash /freqtrade/user_data/run_bt.sh
#
# Or copy this script into the mounted volume first:
#   cp scripts/run-5yr-backtests.sh freqtrade/user_data/run_bt.sh
#   docker exec -d freqtrade bash /freqtrade/user_data/run_bt.sh
#
# Note: ./scripts/ is NOT volume-mounted into the container.
#       Only ./freqtrade/user_data/ and ./freqtrade/config/ are.
# ============================================================
set -euo pipefail

STRATEGIES=("A52Strategy" "OPTStrategy" "A51Strategy" "A31Strategy" "AdaptiveMLStrategy")
TIMERANGE="${1:-20230101-20260101}"
SUMMARY="/freqtrade/user_data/backtest_results/backtest_5yr_summary.txt"

echo "===== CC Backtest Suite =====" >"$SUMMARY"
echo "Date: $(date)" >>"$SUMMARY"
echo "Range: $TIMERANGE" >>"$SUMMARY"
echo "Pairs: ETH BTC SOL BNB XRP DOGE" >>"$SUMMARY"
echo "" >>"$SUMMARY"

for STRAT in "${STRATEGIES[@]}"; do
	echo "================================================================" >>"$SUMMARY"
	echo "  $STRAT" >>"$SUMMARY"
	echo "================================================================" >>"$SUMMARY"
	echo "[$(date)] Starting..." >>"$SUMMARY"

	freqtrade backtesting \
		--config /freqtrade/config/config_backtest.json \
		--strategy "$STRAT" \
		--timeframe 5m \
		--timerange "$TIMERANGE" \
		--enable-protections \
		--export trades \
		2>&1 >>"$SUMMARY"

	echo "[$(date)] Finished (exit: $?)" >>"$SUMMARY"
	echo "" >>"$SUMMARY"
done

echo "===== ALL BACKTESTS COMPLETE =====" >>"$SUMMARY"
echo "Finished at: $(date)" >>"$SUMMARY"

#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# diff-configs.sh — Compare live Freqtrade config vs reference
#
# Usage:
#   ./scripts/diff-configs.sh              # diff live vs reference
#   ./scripts/diff-configs.sh --snapshot   # save current as reference
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$REPO_ROOT/freqtrade/config"
REF_FILE="$CONFIG_DIR/config_reference.json"
LIVE_CONFIG="$CONFIG_DIR/config.json"
BT_CONFIG="$CONFIG_DIR/config_backtest.json"

# Keys to compare (security-sensitive keys excluded)
COMPARE_KEYS=(
	".trading_mode"
	".margin_mode"
	".max_open_trades"
	".stake_currency"
	".stake_amount"
	".dry_run"
	".exchange.pair_whitelist"
	".exchange.pair_blacklist"
	".pairlists"
	".timeframe"
	".startup_candle_count"
	".order_types"
	".entry_pricing"
	".exit_pricing"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Check for jq
if ! command -v jq &>/dev/null; then
	echo "Error: jq is required. Install with: brew install jq (macOS) or apt install jq (Linux)"
	exit 1
fi

snapshot() {
	echo "📸 Saving current config as reference..."
	# Extract only the keys we care about (strip secrets)
	jq '{
    _snapshot_date: (now | todate),
    _source: "config.json",
    trading_mode, margin_mode, max_open_trades,
    stake_currency, stake_amount, dry_run,
    exchange: { pair_whitelist: .exchange.pair_whitelist, pair_blacklist: .exchange.pair_blacklist },
    pairlists, timeframe, startup_candle_count,
    order_types, entry_pricing, exit_pricing
  }' "$LIVE_CONFIG" >"$REF_FILE"
	echo -e "${GREEN}✅ Reference saved: $REF_FILE${NC}"
	echo "   $(jq -r '._snapshot_date' "$REF_FILE")"
}

diff_configs() {
	if [[ ! -f $REF_FILE ]]; then
		echo -e "${YELLOW}⚠️  No reference config found. Creating one now...${NC}"
		snapshot
		echo ""
	fi

	echo "═══════════════════════════════════════════════════"
	echo " Config Diff: live vs reference"
	echo "═══════════════════════════════════════════════════"
	echo ""

	local ref_date
	ref_date=$(jq -r '._snapshot_date // "unknown"' "$REF_FILE")
	echo "Reference: $ref_date"
	echo ""

	local diffs=0

	for key in "${COMPARE_KEYS[@]}"; do
		local ref_val live_val
		ref_val=$(jq -c "$key // null" "$REF_FILE" 2>/dev/null)
		live_val=$(jq -c "$key // null" "$LIVE_CONFIG" 2>/dev/null)

		if [[ $ref_val != "$live_val" ]]; then
			echo -e "${RED}CHANGED${NC} $key"
			echo "  ref:  $ref_val"
			echo "  live: $live_val"
			diffs=$((diffs + 1))
		fi
	done

	if [[ $diffs -eq 0 ]]; then
		echo -e "${GREEN}✅ No config drift detected.${NC}"
	else
		echo ""
		echo -e "${YELLOW}⚠️  $diffs key(s) differ from reference.${NC}"
	fi

	# Also check live vs backtest pair alignment
	echo ""
	echo "── Pair Alignment ──"
	local live_pairs bt_pairs
	live_pairs=$(jq -c '.exchange.pair_whitelist | sort' "$LIVE_CONFIG")
	bt_pairs=$(jq -c '.exchange.pair_whitelist | sort' "$BT_CONFIG")

	if [[ $live_pairs == "$bt_pairs" ]]; then
		echo -e "${GREEN}✅ config.json ↔ config_backtest.json pairs match${NC}"
	else
		echo -e "${RED}❌ config.json ↔ config_backtest.json pairs DIFFER${NC}"
		echo "  live: $live_pairs"
		echo "  bt:   $bt_pairs"
	fi

	# Check against pair_universe.json
	local universe_path="$CONFIG_DIR/pair_universe.json"
	if [[ -f $universe_path ]]; then
		local universe_pairs
		universe_pairs=$(jq -c '.pairs | sort' "$universe_path")
		if [[ $live_pairs == "$universe_pairs" ]]; then
			echo -e "${GREEN}✅ config.json ↔ pair_universe.json match${NC}"
		else
			echo -e "${RED}❌ config.json ↔ pair_universe.json DIFFER${NC}"
			echo "  live:     $live_pairs"
			echo "  universe: $universe_pairs"
		fi
	fi
}

case "${1-}" in
--snapshot)
	snapshot
	;;
*)
	diff_configs
	;;
esac

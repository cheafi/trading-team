"""
Unit tests for AdaptiveMLStrategy core logic.
Tests regime detection, discipline gates, Kelly sizing,
and decision journal without running a full Freqtrade instance.

Run: python -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Add strategy directory to path so we can import the strategy
STRATEGY_DIR = Path(__file__).parent.parent / "freqtrade" / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))


# ─── Helpers ────────────────────────────────────────────────────

def make_ohlcv(n=300, base_price=3000.0, seed=42):
    """Generate realistic OHLCV data for testing."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="5min")
    close = base_price + np.cumsum(rng.randn(n) * 10)
    high = close + rng.uniform(5, 20, n)
    low = close - rng.uniform(5, 20, n)
    opn = close + rng.randn(n) * 5
    volume = rng.uniform(100, 10000, n)
    return pd.DataFrame({
        "date": dates,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ─── Regime Detection ──────────────────────────────────────────

class TestRegimeDetection:
    """Test that regime classification produces valid outputs."""

    def test_regime_values_in_range(self):
        """Regimes must be 0, 1, 2, or 3."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        df = make_ohlcv(300)
        result = strategy._detect_regime(df)
        unique = set(result["regime"].dropna().unique())
        assert unique.issubset({0, 1, 2, 3}), f"Unexpected regimes: {unique}"

    def test_sub_regime_values_in_range(self):
        """Sub-regimes must be 0-7."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        df = make_ohlcv(300)
        result = strategy._detect_regime(df)
        unique = set(result["sub_regime"].dropna().unique())
        assert unique.issubset(set(range(8))), f"Unexpected sub-regimes: {unique}"

    def test_default_regime_is_ranging(self):
        """Flat data should mostly be classified as RANGING (2)."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        # Generate very flat price data
        df = make_ohlcv(300, base_price=3000.0)
        df["close"] = 3000.0 + np.random.randn(300) * 0.1  # essentially flat
        df["high"] = df["close"] + 0.5
        df["low"] = df["close"] - 0.5
        df["open"] = df["close"]
        result = strategy._detect_regime(df)
        # Majority should be ranging
        ranging_pct = (result["regime"] == 2).mean()
        assert ranging_pct > 0.5, f"Only {ranging_pct:.0%} ranging for flat data"

    def test_no_lookahead_in_regime(self):
        """Regime at row N must not depend on rows > N (no lookahead)."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        df = make_ohlcv(300)
        full_result = strategy._detect_regime(df.copy())
        # Truncate to first 200 rows and re-detect
        partial_result = strategy._detect_regime(df.iloc[:200].copy())
        # First 200 regimes should match (row 60+ to allow warmup)
        np.testing.assert_array_equal(
            full_result["regime"].values[60:200],
            partial_result["regime"].values[60:200],
            err_msg="Regime detection has lookahead bias",
        )


# ─── Session Detection ─────────────────────────────────────────

class TestSessionDetection:
    """Test session classification logic."""

    def test_asia_session(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        t = datetime(2025, 6, 15, 3, 0)  # 03:00 UTC
        assert strategy._get_current_session(t) == "asia"

    def test_europe_session(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        t = datetime(2025, 6, 15, 10, 0)  # 10:00 UTC
        assert strategy._get_current_session(t) == "europe"

    def test_us_session(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        t = datetime(2025, 6, 15, 16, 0)  # 16:00 UTC
        assert strategy._get_current_session(t) == "us"

    def test_overlap_session(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        t = datetime(2025, 6, 15, 23, 0)  # 23:00 UTC
        assert strategy._get_current_session(t) == "overlap"


# ─── Regime Params ──────────────────────────────────────────────

class TestRegimeParams:
    """Test regime parameter loading and defaults."""

    def test_default_params_all_regimes(self):
        """Every regime 0-3 must have valid default params."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        for regime in range(4):
            params = strategy._get_regime_params(regime)
            assert "c" in params, f"Regime {regime} missing 'c'"
            assert "sl" in params, f"Regime {regime} missing 'sl'"
            assert "strategy" in params, f"Regime {regime} missing 'strategy'"
            assert params["sl"] < 0, f"Regime {regime} SL must be negative"
            assert 0 < params["c"] < 1, f"Regime {regime} c out of range"

    def test_r2_strategy_is_a52(self):
        """R2 (the only active regime) should default to A52."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        params = strategy._get_regime_params(2)
        assert params["strategy"] == "A52"

    def test_loaded_params_override_defaults(self):
        """best_params.json should override hardcoded defaults."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        strategy._best_params = {
            "2": {"c": 0.25, "e": -0.10, "sl": -0.008, "strategy": "A52"},
        }
        params = strategy._get_regime_params(2)
        assert params["c"] == 0.25
        assert params["sl"] == -0.008


# ─── Discipline Gates ──────────────────────────────────────────

class TestDisciplineGates:
    """Test that discipline systems block/allow trades correctly."""

    def _make_strategy(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        # Mock dp to avoid Freqtrade runtime dependency
        strategy.dp = MagicMock()
        strategy.dp.get_analyzed_dataframe.return_value = (make_ohlcv(300), None)
        return strategy

    def test_kill_switch_blocks_entry(self, tmp_path):
        """Kill switch file must block all entries."""
        import AdaptiveMLStrategy as mod
        old_path = mod.KILL_SWITCH_PATH
        mod.KILL_SWITCH_PATH = tmp_path / "kill_switch"
        mod.KILL_SWITCH_PATH.touch()
        mod.DECISION_JOURNAL_PATH = tmp_path / "journal.jsonl"
        mod.REJECTION_LOG_PATH = tmp_path / "rejections.json"
        try:
            strategy = self._make_strategy()
            result = strategy.confirm_trade_entry(
                pair="ETH/USDT:USDT",
                order_type="limit",
                amount=100,
                rate=3000.0,
                time_in_force="GTC",
                current_time=datetime(2025, 6, 15, 12, 0),
                entry_tag="ml_a52_r2_short",
                side="short",
            )
            assert result is False, "Kill switch should block entry"
        finally:
            mod.KILL_SWITCH_PATH = old_path

    def test_non_futures_pair_blocked(self, tmp_path):
        """Spot pairs (no :USDT suffix) must be blocked."""
        import AdaptiveMLStrategy as mod
        old_ks = mod.KILL_SWITCH_PATH
        mod.KILL_SWITCH_PATH = tmp_path / "kill_switch_doesnt_exist"
        mod.DECISION_JOURNAL_PATH = tmp_path / "journal.jsonl"
        mod.REJECTION_LOG_PATH = tmp_path / "rejections.json"
        try:
            strategy = self._make_strategy()
            result = strategy.confirm_trade_entry(
                pair="ETH/USDT",  # spot pair — no :USDT
                order_type="limit",
                amount=100,
                rate=3000.0,
                time_in_force="GTC",
                current_time=datetime(2025, 6, 15, 12, 0),
                entry_tag="ml_a52_r2_short",
                side="short",
            )
            assert result is False, "Spot pair should be blocked"
        finally:
            mod.KILL_SWITCH_PATH = old_ks

    def test_consecutive_loss_cooldown(self, tmp_path):
        """After N consecutive losses, entries should be blocked."""
        import AdaptiveMLStrategy as mod
        old_ks = mod.KILL_SWITCH_PATH
        mod.KILL_SWITCH_PATH = tmp_path / "kill_switch_doesnt_exist"
        mod.DECISION_JOURNAL_PATH = tmp_path / "journal.jsonl"
        mod.REJECTION_LOG_PATH = tmp_path / "rejections.json"
        try:
            strategy = self._make_strategy()
            strategy._consecutive_losses = 10  # well above default threshold of 5
            strategy._last_trade_date = datetime(2025, 6, 15).date()
            result = strategy.confirm_trade_entry(
                pair="ETH/USDT:USDT",
                order_type="limit",
                amount=100,
                rate=3000.0,
                time_in_force="GTC",
                current_time=datetime(2025, 6, 15, 12, 0),
                entry_tag="ml_a52_r2_short",
                side="short",
            )
            assert result is False, "Should be in cooldown after 10 losses"
        finally:
            mod.KILL_SWITCH_PATH = old_ks

    def test_daily_loss_limit(self, tmp_path):
        """Daily loss limit should block entries."""
        import AdaptiveMLStrategy as mod
        old_ks = mod.KILL_SWITCH_PATH
        mod.KILL_SWITCH_PATH = tmp_path / "kill_switch_doesnt_exist"
        mod.DECISION_JOURNAL_PATH = tmp_path / "journal.jsonl"
        mod.REJECTION_LOG_PATH = tmp_path / "rejections.json"
        try:
            strategy = self._make_strategy()
            strategy._daily_pnl = -0.05  # 5% daily loss
            strategy._last_trade_date = datetime(2025, 6, 15).date()
            result = strategy.confirm_trade_entry(
                pair="ETH/USDT:USDT",
                order_type="limit",
                amount=100,
                rate=3000.0,
                time_in_force="GTC",
                current_time=datetime(2025, 6, 15, 12, 0),
                entry_tag="ml_a52_r2_short",
                side="short",
            )
            assert result is False, "Should be blocked by daily loss limit"
        finally:
            mod.KILL_SWITCH_PATH = old_ks


# ─── Discipline State Persistence ──────────────────────────────

class TestDisciplinePersistence:
    """Test that discipline state survives save/restore cycle."""

    def test_save_and_load_discipline_state(self, tmp_path):
        """Discipline state should persist to disk and be restorable."""
        import AdaptiveMLStrategy as mod
        old_path = mod.DISCIPLINE_STATE_PATH
        mod.DISCIPLINE_STATE_PATH = tmp_path / "discipline_state.json"
        try:
            strategy = mod.AdaptiveMLStrategy(
                config={"exchange": {"name": "binance"}}
            )
            strategy._consecutive_losses = 3
            strategy._daily_pnl = -0.015
            strategy._daily_trades = 7
            strategy._recent_results = [-0.01, 0.02, -0.005]
            strategy._save_discipline_state()

            # Create fresh strategy and restore
            strategy2 = mod.AdaptiveMLStrategy(
                config={"exchange": {"name": "binance"}}
            )
            strategy2._load_discipline_state()

            assert strategy2._consecutive_losses == 3
            assert abs(strategy2._daily_pnl - (-0.015)) < 1e-6
            assert strategy2._daily_trades == 7
            assert len(strategy2._recent_results) == 3
        finally:
            mod.DISCIPLINE_STATE_PATH = old_path

    def test_stale_state_resets_on_new_day(self, tmp_path):
        """State from yesterday should not be restored."""
        import AdaptiveMLStrategy as mod
        old_path = mod.DISCIPLINE_STATE_PATH
        mod.DISCIPLINE_STATE_PATH = tmp_path / "discipline_state.json"
        try:
            # Write state with yesterday's date
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            state = {
                "date": yesterday,
                "consecutive_losses": 5,
                "daily_pnl": -0.03,
                "daily_trades": 10,
                "recent_results": [],
                "saved_at": datetime.utcnow().isoformat(),
            }
            with open(mod.DISCIPLINE_STATE_PATH, "w") as f:
                json.dump(state, f)

            strategy = mod.AdaptiveMLStrategy(
                config={"exchange": {"name": "binance"}}
            )
            strategy._load_discipline_state()

            # Should NOT have restored yesterday's counters
            assert strategy._consecutive_losses == 0
            assert strategy._daily_pnl == 0.0
        finally:
            mod.DISCIPLINE_STATE_PATH = old_path


# ─── Kelly Sizing ───────────────────────────────────────────────

class TestKellySizing:
    """Test position sizing logic."""

    def test_size_reduces_after_losses(self):
        """Anti-martingale: size should decrease after consecutive losses."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        # Base size with no losses
        strategy._consecutive_losses = 0
        size_0 = strategy.custom_stake_amount(
            pair="ETH/USDT:USDT",
            current_time=datetime(2025, 6, 15, 12, 0),
            current_rate=3000.0,
            proposed_stake=200.0,
            min_stake=10.0,
            max_stake=1000.0,
            leverage=1,
            entry_tag="ml_a52_r2_short",
            side="short",
        )
        # Size after 3 losses
        strategy._consecutive_losses = 3
        size_3 = strategy.custom_stake_amount(
            pair="ETH/USDT:USDT",
            current_time=datetime(2025, 6, 15, 12, 0),
            current_rate=3000.0,
            proposed_stake=200.0,
            min_stake=10.0,
            max_stake=1000.0,
            leverage=1,
            entry_tag="ml_a52_r2_short",
            side="short",
        )
        assert size_3 < size_0, (
            f"Size after 3 losses ({size_3:.2f}) should be < "
            f"base size ({size_0:.2f})"
        )

    def test_size_clamped(self):
        """Position size multiplier should be clamped to [0.05, 0.80]."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        # Even with extreme params, size should be bounded
        strategy._best_params = {
            "2": {"c": 999.0, "e": 0, "sl": -0.01, "strategy": "A52",
                  "kelly_fraction": 999.0, "size_adj": 999.0},
        }
        size = strategy.custom_stake_amount(
            pair="ETH/USDT:USDT",
            current_time=datetime(2025, 6, 15, 12, 0),
            current_rate=3000.0,
            proposed_stake=200.0,
            min_stake=10.0,
            max_stake=1000.0,
            leverage=1,
            entry_tag="ml_a52_r2_short",
            side="short",
        )
        assert size <= 200.0 * 0.80, f"Size {size:.2f} exceeds 80% cap"
        assert size >= 200.0 * 0.05, f"Size {size:.2f} below 5% floor"


# ─── Feature Snapshot ──────────────────────────────────────────

class TestFeatureSnapshot:
    """Test feature extraction for decision journal."""

    def test_snap_features_extracts_known_keys(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        row = pd.Series({
            "adx": 25.5,
            "rsi": 45.2,
            "regime": 2,
            "direction_score": -0.3,
            "volume": 5000.0,
            "volume_sma": 4000.0,
        })
        snap = strategy._snap_features(row)
        assert snap["adx"] == 25.5
        assert snap["regime"] == 2
        assert snap["direction_score"] == -0.3

    def test_snap_features_handles_nan(self):
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        row = pd.Series({
            "adx": np.nan,
            "rsi": 45.2,
            "regime": 2,
        })
        snap = strategy._snap_features(row)
        assert "adx" not in snap, "NaN values should be excluded"
        assert snap["rsi"] == 45.2


# ─── Custom Stoploss ───────────────────────────────────────────

class TestCustomStoploss:
    """Test MFE-calibrated stoploss behavior."""

    def test_winning_trade_trails(self):
        """Big winners should get trailing stop."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        trade = MagicMock()
        trade.enter_tag = "ml_a52_r2_short"
        trade.open_date_utc = datetime(2025, 6, 15, 12, 0)

        sl = strategy.custom_stoploss(
            pair="ETH/USDT:USDT",
            trade=trade,
            current_time=datetime(2025, 6, 15, 12, 30),
            current_rate=2950.0,
            current_profit=0.02,  # 2% profit
            after_fill=True,
        )
        # Trail should lock in some gain
        assert sl > -0.02, f"Trailing stop {sl} too wide for 2% winner"

    def test_losing_trade_uses_base_sl(self):
        """Early losing trade should use base stoploss."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        trade = MagicMock()
        trade.enter_tag = "ml_a52_r2_short"
        trade.open_date_utc = datetime(2025, 6, 15, 12, 0)

        sl = strategy.custom_stoploss(
            pair="ETH/USDT:USDT",
            trade=trade,
            current_time=datetime(2025, 6, 15, 12, 5),
            current_rate=3010.0,
            current_profit=-0.003,  # small loss, early
            after_fill=True,
        )
        assert sl < -0.003, f"Base SL {sl} too tight for early trade"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

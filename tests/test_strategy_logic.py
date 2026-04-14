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

# conftest.py handles all mocking and path setup — just import directly
import AdaptiveMLStrategy as mod
from AdaptiveMLStrategy import AdaptiveMLStrategy


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


# ─── Max DD Halt ────────────────────────────────────────────────

class TestMaxDDHalt:
    """Test strategy-level max drawdown circuit breaker."""

    def test_dd_halt_triggers_at_20pct(self, tmp_path):
        """20% drawdown should return 'halt' and create kill switch."""
        import AdaptiveMLStrategy as mod
        old_ks = mod.KILL_SWITCH_PATH
        mod.KILL_SWITCH_PATH = tmp_path / "kill_switch"
        try:
            strategy = mod.AdaptiveMLStrategy(
                config={"exchange": {"name": "binance"}}
            )
            # Simulate equity curve: peak at 0.10, current at -0.12
            # DD = (0.10 - (-0.12)) / 0.10 = 220% — well above 20%
            strategy._equity_curve = [
                0.0, 0.02, 0.05, 0.08, 0.10,  # peak
                0.06, 0.02, -0.02, -0.06, -0.12,  # crash
            ]
            result = strategy._check_max_drawdown(datetime(2025, 6, 15))
            assert result == "halt"
            assert mod.KILL_SWITCH_PATH.exists(), "Kill switch should be created"
        finally:
            mod.KILL_SWITCH_PATH = old_ks

    def test_dd_warn_at_15pct(self):
        """15% drawdown should return 'warn' but not halt."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        # Peak at 1.0, current at 0.84 → DD = 16%
        strategy._equity_curve = [
            0.0, 0.2, 0.5, 0.8, 1.0, 0.95, 0.90, 0.84,
        ]
        result = strategy._check_max_drawdown(datetime(2025, 6, 15))
        assert result == "warn"

    def test_dd_ok_for_normal_curve(self):
        """Small DD should return 'ok'."""
        from AdaptiveMLStrategy import AdaptiveMLStrategy
        strategy = AdaptiveMLStrategy(config={"exchange": {"name": "binance"}})
        strategy._equity_curve = [0.0, 0.01, 0.02, 0.03, 0.025, 0.03]
        result = strategy._check_max_drawdown(datetime(2025, 6, 15))
        assert result == "ok"


# ─── HMAC Model Integrity ──────────────────────────────────────

class TestModelHMAC:
    """Test HMAC verification for model files."""

    def test_tofu_creates_hmac(self, tmp_path):
        """First load should create HMAC (trust on first use)."""
        import AdaptiveMLStrategy as mod
        old_hmac = mod.MODEL_HMAC_PATH
        mod.MODEL_HMAC_PATH = tmp_path / "model_hmac.json"
        try:
            result = mod.AdaptiveMLStrategy._verify_model_hmac(
                "test_model.pkl", b"test data"
            )
            assert result is True
            assert mod.MODEL_HMAC_PATH.exists()
            stored = json.loads(mod.MODEL_HMAC_PATH.read_text())
            assert "test_model.pkl" in stored
        finally:
            mod.MODEL_HMAC_PATH = old_hmac

    def test_hmac_rejects_tampered_data(self, tmp_path):
        """Modified file should fail HMAC verification."""
        import AdaptiveMLStrategy as mod
        old_hmac = mod.MODEL_HMAC_PATH
        mod.MODEL_HMAC_PATH = tmp_path / "model_hmac.json"
        try:
            # First load — TOFU
            mod.AdaptiveMLStrategy._verify_model_hmac(
                "test.pkl", b"original data"
            )
            # Second load with different data — should fail
            result = mod.AdaptiveMLStrategy._verify_model_hmac(
                "test.pkl", b"tampered data"
            )
            assert result is False, "Tampered data should fail HMAC check"
        finally:
            mod.MODEL_HMAC_PATH = old_hmac


# ─── Correlation Groups ────────────────────────────────────────

class TestCorrelationGroups:
    """Test correlation group configuration."""

    def test_all_pairs_in_groups(self):
        """All 6 whitelisted pairs should be in a correlation group."""
        from AdaptiveMLStrategy import CORRELATION_GROUPS
        all_pairs = set()
        for members in CORRELATION_GROUPS.values():
            all_pairs.update(members)
        expected = {
            "ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT",
            "BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
        }
        assert expected == all_pairs, f"Missing pairs: {expected - all_pairs}"


# ─── Regime Engine Module Tests ─────────────────────────────────

class TestRegimeEngine:
    """Test the extracted regime_engine module directly."""

    def test_detect_regime_returns_all_columns(self):
        """detect_regime should add all expected columns."""
        from regime_engine import detect_regime
        df = make_ohlcv(300)
        result = detect_regime(df, lookback=50)
        expected_cols = [
            "regime", "sub_regime", "adx", "atr_norm",
            "ema_slope", "bb_width", "vol_ratio",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_rule_based_regime_values(self):
        """rule_based_regime should produce values 0-3."""
        from regime_engine import detect_regime
        df = make_ohlcv(300)
        result = detect_regime(df)
        unique = set(result["regime"].dropna().unique())
        assert unique.issubset({0, 1, 2, 3})

    def test_get_regime_params_defaults(self):
        """get_regime_params returns defaults when no best_params."""
        from regime_engine import get_regime_params
        p = get_regime_params(2, best_params=None)
        assert p["strategy"] == "A52"
        assert "sl" in p
        assert "roi_table" in p

    def test_get_regime_params_from_best(self):
        """get_regime_params uses best_params when provided."""
        from regime_engine import get_regime_params
        bp = {"2": {"strategy": "CUSTOM", "c": 0.99, "sl": -0.01}}
        p = get_regime_params(2, best_params=bp)
        assert p["strategy"] == "CUSTOM"
        assert p["c"] == 0.99

    def test_get_current_session_all_hours(self):
        """get_current_session covers all 24 hours."""
        from regime_engine import get_current_session
        sessions = set()
        for h in range(24):
            mock_time = MagicMock()
            mock_time.hour = h
            sessions.add(get_current_session(mock_time))
        # Should have at least 3 distinct sessions
        assert len(sessions) >= 3

    def test_classify_sub_regime_length(self):
        """Sub-regime array has same length as input."""
        from regime_engine import detect_regime
        df = make_ohlcv(300)
        result = detect_regime(df)
        assert len(result["sub_regime"]) == 300


# ─── Discipline Engine Module Tests ─────────────────────────────

class TestDisciplineEngine:
    """Test the extracted discipline_engine module directly."""

    def test_save_and_load_discipline_state(self):
        """State should round-trip through save/load."""
        from discipline_engine import (
            save_discipline_state, load_discipline_state,
        )
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            state = {
                "consecutive_losses": 3,
                "daily_pnl": -0.015,
                "daily_trades": 7,
                "recent_results": [0.01, -0.02, 0.005],
            }
            save_discipline_state(path, state, max_recent=20)
            assert path.exists()

            restored = {
                "consecutive_losses": 0,
                "daily_pnl": 0.0,
                "daily_trades": 0,
                "recent_results": [],
            }
            restored = load_discipline_state(path, restored)
            assert restored["consecutive_losses"] == 3
            assert restored["daily_trades"] == 7
            assert len(restored["recent_results"]) == 3
        finally:
            if path.exists():
                path.unlink()

    def test_check_max_drawdown_ok(self):
        """No halt when equity is healthy."""
        from discipline_engine import check_max_drawdown
        # Peak at 1.0, current at 0.95 → 5% DD (well below 20%)
        curve = [0.0, 0.3, 0.5, 0.8, 1.0, 0.95]
        ks = Path(tempfile.mktemp())
        result = check_max_drawdown(curve, ks, datetime.utcnow())
        assert result == "ok"
        assert not ks.exists()

    def test_check_max_drawdown_halt(self):
        """Halt when drawdown exceeds threshold."""
        from discipline_engine import check_max_drawdown
        # Peak at 1.0, current at 0.7 → 30% DD
        curve = [0.0, 0.5, 1.0, 0.9, 0.7]
        ks = Path(tempfile.mktemp())
        try:
            result = check_max_drawdown(
                curve, ks, datetime.utcnow(),
                max_dd_halt=0.20,
            )
            assert result == "halt"
            assert ks.exists()
        finally:
            if ks.exists():
                ks.unlink()

    def test_check_max_drawdown_warn(self):
        """Warning when DD is between warn and halt."""
        from discipline_engine import check_max_drawdown
        # Peak at 1.0, current at 0.83 → 17% DD
        curve = [0.0, 0.5, 1.0, 0.9, 0.83]
        ks = Path(tempfile.mktemp())
        result = check_max_drawdown(
            curve, ks, datetime.utcnow(),
            max_dd_halt=0.20, max_dd_warn=0.15,
        )
        assert result == "warn"
        assert not ks.exists()

    def test_snap_features(self):
        """snap_features extracts expected keys."""
        from discipline_engine import snap_features
        row = {
            "adx": 25.5, "rsi": 45.2, "regime": 2,
            "direction_score": -0.35, "volume": 5000.0,
            "volume_sma": 3000.0, "bb_width": 2.1,
        }
        snap = snap_features(row)
        assert snap["adx"] == 25.5
        assert snap["regime"] == 2
        assert snap["direction_score"] == -0.35

    def test_log_decision_writes_jsonl(self):
        """log_decision should append JSONL entries."""
        from discipline_engine import log_decision
        journal = Path(tempfile.mktemp(suffix=".jsonl"))
        rejection = Path(tempfile.mktemp(suffix=".json"))
        try:
            log_decision(
                "ETH/USDT:USDT", "short", "reject", "test_reason",
                datetime.utcnow(), journal, rejection,
                rejection_log=[], max_rejections=100,
            )
            assert journal.exists()
            with open(journal) as f:
                lines = f.readlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["decision"] == "reject"
            assert entry["pair"] == "ETH/USDT:USDT"
        finally:
            if journal.exists():
                journal.unlink()
            if rejection.exists():
                rejection.unlink()

    def test_check_correlation_no_freqtrade(self):
        """Correlation check fails open without freqtrade."""
        from discipline_engine import check_correlation_exposure
        groups = {
            "layer1": ["ETH/USDT:USDT", "BTC/USDT:USDT"],
        }
        # Should fail open (return True) when Trade import fails
        assert check_correlation_exposure(
            "ETH/USDT:USDT", "short", groups, 2
        ) is True


# ─── Walk-Forward Validation Tests ──────────────────────────────

class TestWalkForward:
    """Test the upgraded expanding window walk-forward validation."""

    def _make_trades(self, n=200, base_wr=0.55):
        """Generate mock trades for WF validation."""
        rng = np.random.RandomState(42)
        trades = []
        for i in range(n):
            win = rng.random() < base_wr
            profit = abs(rng.normal(0.003, 0.002)) if win else -abs(rng.normal(0.004, 0.002))
            trades.append({
                "open_timestamp": i * 300000,
                "open_date": f"2025-01-{(i // 10) + 1:02d}",
                "profit_ratio": profit,
                "trade_duration": rng.randint(5, 120),
            })
        return trades

    def test_expanding_window_method(self):
        """Walk-forward should use expanding window method."""
        from ml_analyzer import walk_forward_validate
        trades = self._make_trades(200)
        result = walk_forward_validate(trades, n_windows=5)
        assert result is not None
        assert result["method"] == "expanding_window"

    def test_fold_details_present(self):
        """Each fold should have details with train/test sizes."""
        from ml_analyzer import walk_forward_validate
        trades = self._make_trades(200)
        result = walk_forward_validate(trades, n_windows=5)
        assert "folds" in result
        assert len(result["folds"]) >= 3
        for fold in result["folds"]:
            assert "train_size" in fold
            assert "test_size" in fold
            assert fold["train_size"] > 0
            assert fold["test_size"] > 0

    def test_expanding_train_grows(self):
        """Training set should grow across folds (expanding window)."""
        from ml_analyzer import walk_forward_validate
        trades = self._make_trades(300)
        result = walk_forward_validate(trades, n_windows=5)
        assert result is not None
        sizes = [f["train_size"] for f in result["folds"]]
        # Each fold's training set should be larger than previous
        for i in range(1, len(sizes)):
            assert sizes[i] > sizes[i - 1], (
                f"Fold {i+1} train ({sizes[i]}) should be > "
                f"fold {i} train ({sizes[i-1]})"
            )

    def test_degradation_slope_present(self):
        """Result should include degradation_slope metric."""
        from ml_analyzer import walk_forward_validate
        trades = self._make_trades(200)
        result = walk_forward_validate(trades, n_windows=5)
        assert "degradation_slope" in result
        assert isinstance(result["degradation_slope"], float)

    def test_insufficient_data_returns_none(self):
        """Too few trades should return None."""
        from ml_analyzer import walk_forward_validate
        result = walk_forward_validate(self._make_trades(50), n_windows=5)
        assert result is None

    def test_robustness_flag(self):
        """is_robust should be a boolean."""
        from ml_analyzer import walk_forward_validate
        trades = self._make_trades(200)
        result = walk_forward_validate(trades, n_windows=5)
        assert isinstance(result["is_robust"], bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


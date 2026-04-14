"""
conftest.py — Patch Freqtrade and model paths before strategy import.

This allows tests to run locally (macOS) without Docker or Freqtrade installed.
The strategy module references /freqtrade/user_data/ml_models at import time,
which doesn't exist on the host. We redirect all paths to a temp directory.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ─── Create temp model dir before anything imports the strategy ──
_TMPDIR = tempfile.mkdtemp(prefix="cc_test_models_")
_TMP_MODEL_DIR = Path(_TMPDIR)

# Set env var that overrides MODEL_DIR if the strategy reads it
os.environ["MODEL_DIR"] = _TMPDIR

# ─── Mock freqtrade modules ─────────────────────────────────────

# Create a proper mock IStrategy base class
class _MockIStrategy:
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    minimal_roi = {}
    stoploss = -0.025
    use_custom_stoploss = True
    trailing_stop = False
    startup_candle_count = 200
    dp = MagicMock()

    def __init__(self, config=None, **kwargs):
        pass


class _MockDecimalParameter:
    def __init__(self, *args, **kwargs):
        self.value = kwargs.get("default", 0.5)

    def __float__(self):
        return float(self.value)


class _MockIntParameter:
    def __init__(self, *args, **kwargs):
        self.value = kwargs.get("default", 50)

    def __int__(self):
        return int(self.value)


# Build the mock module
_mock_strategy_module = MagicMock()
_mock_strategy_module.IStrategy = _MockIStrategy
_mock_strategy_module.DecimalParameter = _MockDecimalParameter
_mock_strategy_module.IntParameter = _MockIntParameter

# Register mocks BEFORE any test file imports
sys.modules["freqtrade"] = MagicMock()
sys.modules["freqtrade.strategy"] = _mock_strategy_module
sys.modules["freqtrade.persistence"] = MagicMock()

# ─── Monkey-patch the strategy module's MODEL_DIR ────────────────
# We must patch at the source before import
STRATEGY_DIR = (
    Path(__file__).parent.parent
    / "freqtrade"
    / "user_data"
    / "strategies"
)
sys.path.insert(0, str(STRATEGY_DIR))

# Pre-import patch: override the Path that would fail
import importlib
_strategy_source = STRATEGY_DIR / "AdaptiveMLStrategy.py"

# Read strategy source, replace the hard-coded path
_original_model_dir_line = 'MODEL_DIR = Path("/freqtrade/user_data/ml_models")'
_patched_model_dir_line = f'MODEL_DIR = Path("{_TMPDIR}")'

# We do this by setting an environment-based override
# Actually simpler: just pre-create the directory the strategy wants
# Since macOS blocks /freqtrade, we need a different approach:
# patch Path before import
_original_path_mkdir = Path.mkdir


def _patched_mkdir(self, *args, **kwargs):
    """Redirect /freqtrade paths to temp dir during tests."""
    if str(self).startswith("/freqtrade"):
        redirected = Path(_TMPDIR) / str(self).lstrip("/freqtrade/user_data/ml_models")
        redirected.mkdir(parents=True, exist_ok=True)
        return
    return _original_path_mkdir(self, *args, **kwargs)


Path.mkdir = _patched_mkdir

# Also patch Path("/freqtrade/...").exists() etc by importing and overriding
import AdaptiveMLStrategy as _strategy_mod

# Now redirect all the path constants to temp
_strategy_mod.MODEL_DIR = _TMP_MODEL_DIR
_strategy_mod.BEST_PARAMS_PATH = _TMP_MODEL_DIR / "best_params.json"
_strategy_mod.QUALITY_MODEL_PATH = _TMP_MODEL_DIR / "quality_model.pkl"
_strategy_mod.DISCIPLINE_PATH = _TMP_MODEL_DIR / "discipline_params.json"
_strategy_mod.ANTI_PATTERN_PATH = _TMP_MODEL_DIR / "anti_patterns.json"
_strategy_mod.SHADOW_DIR = _TMP_MODEL_DIR / "shadow"
_strategy_mod.SHADOW_MODEL_PATH = _TMP_MODEL_DIR / "shadow" / "quality_model.pkl"
_strategy_mod.REJECTION_LOG_PATH = _TMP_MODEL_DIR / "rejection_journal.json"
_strategy_mod.DECISION_JOURNAL_PATH = _TMP_MODEL_DIR / "decision_journal.jsonl"
_strategy_mod.TRADE_REPLAY_PATH = _TMP_MODEL_DIR / "trade_replay.json"
_strategy_mod.DISCIPLINE_STATE_PATH = _TMP_MODEL_DIR / "discipline_state.json"
_strategy_mod.KILL_SWITCH_PATH = _TMP_MODEL_DIR / "kill_switch"
_strategy_mod.MODEL_HMAC_PATH = _TMP_MODEL_DIR / "model_hmac.json"

# Restore original mkdir
Path.mkdir = _original_path_mkdir


@pytest.fixture(autouse=True)
def clean_model_dir():
    """Clean up model dir between tests."""
    yield
    # Remove kill switch if created during test
    ks = _TMP_MODEL_DIR / "kill_switch"
    if ks.exists():
        ks.unlink()
    # Remove HMAC file
    hmac_f = _TMP_MODEL_DIR / "model_hmac.json"
    if hmac_f.exists():
        hmac_f.unlink()

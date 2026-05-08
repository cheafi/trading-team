"""
conftest.py — Patch Freqtrade paths for local testing without Docker.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ─── Temp model dir ─────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="cc_test_"))
os.environ["MODEL_DIR"] = str(_TMPDIR)

# ─── Mock freqtrade ─────────────────────────────────────────────


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


_mock_ft = MagicMock()
_mock_ft.IStrategy = _MockIStrategy
_mock_ft.DecimalParameter = _MockDecimalParameter
_mock_ft.IntParameter = _MockIntParameter

sys.modules["freqtrade"] = MagicMock()
sys.modules["freqtrade.strategy"] = _mock_ft
sys.modules["freqtrade.persistence"] = MagicMock()

# ─── Import strategies with patched paths ────────────────────────
STRATEGY_DIR = (
    Path(__file__).resolve().parent.parent / "freqtrade" / "user_data" / "strategies"
)
sys.path.insert(0, str(STRATEGY_DIR))

# Patch Path.mkdir to redirect /freqtrade → temp
_orig_mkdir = Path.mkdir


def _patched_mkdir(self, *args, **kwargs):
    if str(self).startswith("/freqtrade"):
        target = _TMPDIR / str(self).removeprefix(
            "/freqtrade/user_data/ml_models/"
        ).lstrip("/")
        target.mkdir(parents=True, exist_ok=True)
        return
    return _orig_mkdir(self, *args, **kwargs)


Path.mkdir = _patched_mkdir

import AdaptiveMLStrategy as _strat  # noqa: E402
import regime_engine  # noqa: E402
import discipline_engine  # noqa: E402
import log_config  # noqa: E402

Path.mkdir = _orig_mkdir

# Redirect all path constants to temp
for attr in dir(_strat):
    val = getattr(_strat, attr, None)
    if isinstance(val, Path) and str(val).startswith("/freqtrade"):
        setattr(_strat, attr, _TMPDIR / val.name)

# Ensure shadow dir exists
(_TMPDIR / "shadow").mkdir(exist_ok=True)


@pytest.fixture(autouse=True)
def _clean_model_dir():
    """Remove volatile files between tests."""
    yield
    for name in ("kill_switch", "model_hmac.json", "discipline_state.json"):
        f = _TMPDIR / name
        if f.exists():
            f.unlink()

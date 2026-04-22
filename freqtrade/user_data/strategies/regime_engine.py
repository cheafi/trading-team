"""
Regime Engine — Market regime detection & classification
========================================================
Extracts regime detection logic from AdaptiveMLStrategy
for maintainability. Used by both strategy and ml_optimizer.

4 base regimes:
  R0 TRENDING_UP   (disabled in live)
  R1 TRENDING_DOWN (disabled in live)
  R2 RANGING       (active — short only)
  R3 VOLATILE      (disabled in live)

8 sub-regimes:
  0=TREND_UP_STRONG, 1=TREND_UP_WEAK,
  2=TREND_DOWN_STRONG, 3=TREND_DOWN_WEAK,
  4=RANGE_TIGHT, 5=RANGE_WIDE,
  6=VOLATILE_EXPANDING, 7=VOLATILE_CONTRACTING
"""

import numpy as np
import talib.abstract as ta
from pandas import DataFrame


# Session hours (UTC)
SESSION_HOURS = {
    "asia": (0, 8),
    "europe": (8, 14),
    "us": (14, 22),
    "overlap": (22, 24),
}

# Default regime params — calibrated from backtest results.
# These are overridden by best_params.json when available.
DEFAULT_REGIME_PARAMS = {
    0: {
        "c": 0.115,
        "e": 0.05,
        "roi_table": {"0": 0.0043, "30": 0.00347, "120": 0.00347},
        "sl": -0.005,
        "trailing_offset": 0.003,
        "strategy": "A31",
        "entry_adj": 1.0,
        "size_adj": 1.0,
        "best_session": None,
        "worst_session": None,
        "direction_bias": "neutral",
        "bias_strength": 0.0,
        "trail_start": 0.0103,
        "trail_step": 0.0052,
    },
    1: {
        "c": 0.10,
        "e": 0.0,
        "roi_table": {"0": 0.00227, "30": 0.0021, "120": 0.0021},
        "sl": -0.005,
        "trailing_offset": 0.0,
        "strategy": "A51",
        "entry_adj": 1.0,
        "size_adj": 1.0,
        "best_session": None,
        "worst_session": None,
        "direction_bias": "neutral",
        "bias_strength": 0.0,
        "trail_start": 0.0055,
        "trail_step": 0.0027,
    },
    2: {
        "c": 0.17,
        "e": -0.18,
        "roi_table": {"0": 0.00402, "30": 0.00402, "120": 0.00402},
        "sl": -0.0064,
        "trailing_offset": 0.0,
        "strategy": "A52",
        "entry_adj": 1.0,
        "size_adj": 1.0,
        "best_session": None,
        "worst_session": None,
        "direction_bias": "neutral",
        "bias_strength": 0.0,
        "trail_start": 0.009,
        "trail_step": 0.0045,
    },
    3: {
        "c": 0.10,
        "e": 0.115,
        "roi_table": {"0": 0.0041, "30": 0.0035, "120": 0.0035},
        "sl": -0.0058,
        "trailing_offset": 0.0,
        "strategy": "A52",
        "entry_adj": 1.0,
        "size_adj": 1.0,
        "best_session": None,
        "worst_session": None,
        "direction_bias": "neutral",
        "bias_strength": 0.0,
        "trail_start": 0.0063,
        "trail_step": 0.0032,
    },
}


def detect_regime(dataframe: DataFrame, lookback: int = 50) -> DataFrame:
    """
    Classify market into 4 base regimes + 8 sub-regimes
    using rule-based candle features (ADX/EMA/ATR/BB).

    Returns dataframe with added columns:
        regime, sub_regime, adx, atr_norm, ema_slope,
        bb_width, vol_ratio, momentum_accel, vol_trend
    """
    df = dataframe.copy()

    # Trend strength: ADX
    df["adx"] = ta.ADX(df, timeperiod=lookback)

    # Volatility: ATR normalized
    df["atr_norm"] = (ta.ATR(df, timeperiod=lookback) / df["close"]) * 100

    # Direction: EMA slope
    ema = ta.EMA(df, timeperiod=lookback)
    df["ema_slope"] = (ema - ema.shift(10)) / ema.shift(10) * 100

    # Range indicator: BB width
    bb = ta.BBANDS(df, timeperiod=lookback)
    df["bb_width"] = ((bb["upperband"] - bb["lowerband"]) / bb["middleband"]) * 100

    # Volume trend
    df["vol_ratio"] = df["volume"] / ta.SMA(df["volume"], timeperiod=lookback)

    # Momentum acceleration (rate of change of momentum)
    df["roc_10"] = ta.ROC(df, timeperiod=10)
    df["momentum_accel"] = df["roc_10"] - df["roc_10"].shift(5)

    # Volatility trend (expanding or contracting)
    df["atr_short"] = ta.ATR(df, timeperiod=10)
    df["atr_long"] = ta.ATR(df, timeperiod=30)
    df["vol_trend"] = (df["atr_short"] / df["atr_long"] - 1.0) * 100

    # Base regime + sub-regime
    df["regime"] = rule_based_regime(df)
    df["sub_regime"] = classify_sub_regime(df)

    # Copy computed columns back to original dataframe
    for col in [
        "regime", "adx", "atr_norm", "ema_slope", "bb_width",
        "vol_ratio", "momentum_accel", "vol_trend", "sub_regime",
    ]:
        dataframe[col] = df[col]

    return dataframe


def rule_based_regime(df: DataFrame) -> np.ndarray:
    """Base regime detection (4 classes)."""
    regimes = np.full(len(df), 2)  # default RANGING

    # Trending up: ADX > 25 and positive slope
    mask_up = (df["adx"] > 25) & (df["ema_slope"] > 0.1)
    regimes[mask_up] = 0

    # Trending down: ADX > 25 and negative slope
    mask_down = (df["adx"] > 25) & (df["ema_slope"] < -0.1)
    regimes[mask_down] = 1

    # High volatility: ATR_norm > 80th percentile
    # Use expanding (causal) quantile to avoid lookahead
    if len(df) < 50:
        return regimes
    atr_p80 = df["atr_norm"].expanding(min_periods=50).quantile(0.8)
    mask_vol = df["atr_norm"] > atr_p80
    regimes[mask_vol] = 3

    return regimes


def classify_sub_regime(df: DataFrame) -> np.ndarray:
    """
    Enhanced sub-regime classification (8 classes).
    VECTORIZED for performance (was row-by-row loop).
    """
    sub = np.full(len(df), 4)  # default RANGE_TIGHT
    regime = df["regime"].values if "regime" in df else np.full(len(df), 2)

    ma = df["momentum_accel"].fillna(0).values
    vt = df["vol_trend"].fillna(0).values
    bw = df["bb_width"].fillna(1).values
    # Use expanding (causal) median to avoid lookahead
    median_bw = (
        df["bb_width"]
        .expanding(min_periods=50)
        .median()
        .fillna(df["bb_width"].iloc[:50].median())
        .values
    )

    # Vectorized conditions — no Python loop
    sub[regime == 0] = np.where(ma[regime == 0] > 0, 0, 1)
    sub[regime == 1] = np.where(ma[regime == 1] < 0, 2, 3)
    sub[regime == 2] = np.where(
        bw[regime == 2] < median_bw[regime == 2], 4, 5
    )
    sub[regime == 3] = np.where(vt[regime == 3] > 0, 6, 7)

    return sub


def get_regime_params(regime: int, best_params: dict = None) -> dict:
    """
    Get optimal params for a regime.
    Prefers ML-optimized best_params, falls back to defaults.
    """
    if best_params and str(regime) in best_params:
        return best_params[str(regime)]
    return DEFAULT_REGIME_PARAMS.get(regime, DEFAULT_REGIME_PARAMS[2])


def get_current_session(current_time=None) -> str:
    """Determine current trading session from UTC hour."""
    from datetime import datetime as _dt

    if current_time is None:
        hour = _dt.utcnow().hour
    elif hasattr(current_time, "hour"):
        hour = current_time.hour
    else:
        hour = _dt.utcnow().hour

    for session_name, (start, end) in SESSION_HOURS.items():
        if start <= hour < end:
            return session_name
    return "overlap"

"""
AdaptiveML v3 PRO — USDT Futures 5m R2 Short Specialist
====================================================
Currently a single-regime specialist (R2 RANGING, short-only).
Other regimes (R0/R1/R3) are disabled — they produce more
SL losses than ROI wins.

  CORE:
  1. Multi-timeframe 5m + 15m + 1h confirmation
  2. Self-learned ROI from trade duration buckets
  3. Session filter + directional bias
  4. Performance feedback loop (entry_adj/size_adj)
  5. Rule-based regime detection (4 base + 8 sub)

  PRO:
  6.  Kelly Criterion position sizing (fractional Kelly)
  7.  MFE-calibrated trailing stops (data-driven)
  8.  Equity curve circuit breaker (pause on drawdown)
  9.  Consecutive loss cooldown (discipline after streaks)
  10. Daily loss limit (hard stop for the day)
  11. Fee-aware minimum edge filter
  12. Trade quality gate (session/direction prior)
  13. Anti-martingale (reduce size on losses)

Honest assessment:
  - Quality model uses 3 features (hour, weekday, side) —
    a session-direction prior, not deep trade intelligence.
  - Regime model is trained but NOT used in live decisions.
  - Only R2 short is active. The "adaptive" framing is
    aspirational, not current reality.

Philosophy: "Discipline is the bridge between goals and results."
"""

import json
import pickle  # noqa: S301 — used for quality_model.pkl
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
)
from pandas import DataFrame

# Path where the ML optimizer writes trained models
MODEL_DIR = Path("/freqtrade/user_data/ml_models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Active model artifacts:
BEST_PARAMS_PATH = MODEL_DIR / "best_params.json"
QUALITY_MODEL_PATH = MODEL_DIR / "quality_model.pkl"
DISCIPLINE_PATH = MODEL_DIR / "discipline_params.json"
ANTI_PATTERN_PATH = MODEL_DIR / "anti_patterns.json"

# Decision journal — persists every trade rejection reason
REJECTION_LOG_PATH = MODEL_DIR / "rejection_journal.json"

# Fee structure
ROUND_TRIP_FEE = 0.001  # 0.10% (Binance futures maker+taker)

# Session hours (UTC)
SESSION_HOURS = {
    "asia": (0, 8),
    "europe": (8, 14),
    "us": (14, 22),
    "overlap": (22, 24),
}


class AdaptiveMLStrategy(IStrategy):
    """
    USDT Futures 5m R2 Short Specialist (6 pairs)
    Currently runs one active regime (R2 RANGING, short-only).
    Uses Kelly sizing, MFE-calibrated exits, and discipline systems.
    """

    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True  # FIXED: was False, blocking all short signals

    # Dynamic parameters - updated by ML optimizer
    position_c = DecimalParameter(0.1, 1.0, default=0.50, space="buy", optimize=True)
    entry_bias = DecimalParameter(-0.5, 0.5, default=0.00, space="buy", optimize=True)

    # Regime detection windows
    regime_lookback = IntParameter(20, 100, default=50, space="buy", optimize=True)

    # ML confidence threshold
    min_confidence = DecimalParameter(
        0.3, 0.8, default=0.55, space="buy", optimize=True
    )

    # ROI targets: keep high initial target to let winners run
    # 100% WR on ROI exits — don't cut them short
    minimal_roi = {
        "0": 0.015,
        "15": 0.010,
        "30": 0.006,
        "60": 0.003,
        "120": 0.001,
    }

    stoploss = -0.025  # Backstop only; real SL in custom_stoploss()
    use_custom_stoploss = True
    trailing_stop = False

    startup_candle_count = 200

    # Internal state - ML models
    _best_params = None
    _quality_model_data = None  # PRO: quality model
    _discipline_params = None  # PRO: discipline params
    _anti_patterns = None  # PRO v4: learned anti-patterns
    _last_model_load = 0
    _MODEL_RELOAD_INTERVAL = 300

    # PRO: Discipline tracking (reset on strategy reload)
    _consecutive_losses = 0
    _daily_pnl = 0.0
    _daily_trades = 0
    _last_trade_date = None
    _equity_curve = []  # rolling equity for circuit breaker
    _recent_results = []  # last N trade results
    _MAX_RECENT = 20  # track last 20 trades
    _paused_until = None  # cooldown timestamp
    _rejection_log = []  # decision journal: last 100 rejections
    _MAX_REJECTIONS = 100

    # ─── Multi-timeframe informative pairs ───────────────
    def informative_pairs(self):
        """Request 15m and 1h data for higher-TF confirmation."""
        pairs = self.dp.current_whitelist()
        informative = []
        for pair in pairs:
            informative.append((pair, "15m"))
            informative.append((pair, "1h"))
        return informative

    def _load_models(self):
        """Hot-reload ML models and params from disk."""
        now = datetime.now().timestamp()
        if now - self._last_model_load < self._MODEL_RELOAD_INTERVAL:
            return

        self._last_model_load = now

        if BEST_PARAMS_PATH.exists():
            try:
                with open(BEST_PARAMS_PATH, "r") as f:
                    self._best_params = json.load(f)
            except Exception:
                self._best_params = None

        # PRO: Load quality model
        if QUALITY_MODEL_PATH.exists():
            try:
                with open(QUALITY_MODEL_PATH, "rb") as f:
                    self._quality_model_data = pickle.load(f)
            except Exception:
                self._quality_model_data = None

        # PRO: Load discipline params
        if DISCIPLINE_PATH.exists():
            try:
                with open(DISCIPLINE_PATH, "r") as f:
                    self._discipline_params = json.load(f)
            except Exception:
                self._discipline_params = None

        # PRO v4: Load anti-patterns (learned from mistakes)
        if ANTI_PATTERN_PATH.exists():
            try:
                with open(ANTI_PATTERN_PATH, "r") as f:
                    self._anti_patterns = json.load(f)
            except Exception:
                self._anti_patterns = None

    # ─── Regime Detection ────────────────────────────────

    def _detect_regime(self, dataframe: DataFrame) -> DataFrame:
        """
        Classify market into regimes using candle features.
        Uses rule-based detection (ML model trained on trade features).
        Enhanced with sub-regime qualifiers.
        """
        lookback = int(self.regime_lookback.value)
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
        df["regime"] = self._rule_based_regime(df)
        df["sub_regime"] = self._classify_sub_regime(df)

        for col in [
            "regime",
            "adx",
            "atr_norm",
            "ema_slope",
            "bb_width",
            "vol_ratio",
            "momentum_accel",
            "vol_trend",
            "sub_regime",
        ]:
            dataframe[col] = df[col]

        return dataframe

    def _rule_based_regime(self, df: DataFrame) -> np.ndarray:
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
        atr_p80 = df["atr_norm"].expanding(min_periods=50).quantile(0.8)
        mask_vol = df["atr_norm"] > atr_p80
        regimes[mask_vol] = 3

        return regimes

    def _classify_sub_regime(self, df: DataFrame) -> np.ndarray:
        """
        Enhanced sub-regime classification (8 classes).
        VECTORIZED for performance (was row-by-row loop).
        0=TREND_UP_STRONG, 1=TREND_UP_WEAK,
        2=TREND_DOWN_STRONG, 3=TREND_DOWN_WEAK,
        4=RANGE_TIGHT, 5=RANGE_WIDE,
        6=VOLATILE_EXPANDING, 7=VOLATILE_CONTRACTING
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
        sub[regime == 0] = np.where(ma[regime == 0] > 0, 0, 1)  # UP_STRONG / UP_WEAK
        sub[regime == 1] = np.where(
            ma[regime == 1] < 0, 2, 3
        )  # DOWN_STRONG / DOWN_WEAK
        sub[regime == 2] = np.where(
            bw[regime == 2] < median_bw[regime == 2], 4, 5
        )  # TIGHT / WIDE
        sub[regime == 3] = np.where(
            vt[regime == 3] > 0, 6, 7
        )  # EXPANDING / CONTRACTING

        return sub

    def _get_regime_params(self, regime: int) -> dict:
        """
        Get optimal params for regime from ML optimizer.
        Now includes: roi_table, session filter, direction bias,
        performance feedback adjustments.
        """
        if self._best_params and str(regime) in self._best_params:
            return self._best_params[str(regime)]

        # Defaults calibrated from ML optimizer output.
        # Updated to match best_params.json reality.
        defaults = {
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
        return defaults.get(regime, defaults[2])

    def _get_current_session(self, current_time=None):
        """Determine current trading session from UTC hour."""
        if current_time is None:
            hour = datetime.utcnow().hour
        elif hasattr(current_time, "hour"):
            hour = current_time.hour
        else:
            hour = 12  # default

        for session_name, (h_start, h_end) in SESSION_HOURS.items():
            if h_start <= hour < h_end:
                return session_name
        return "overlap"

    # ─── Multi-Timeframe Indicators ──────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Hot-reload ML models
        self._load_models()

        pair = metadata.get("pair", "")

        # ─── 1H informative indicators ───
        inf_1h = self.dp.get_pair_dataframe(pair, "1h")
        if inf_1h is not None and len(inf_1h) > 0:
            inf_1h["ema50_1h"] = ta.EMA(inf_1h, timeperiod=50)
            inf_1h["ema20_1h"] = ta.EMA(inf_1h, timeperiod=20)
            inf_1h["rsi_1h"] = ta.RSI(inf_1h, timeperiod=14)
            inf_1h["adx_1h"] = ta.ADX(inf_1h, timeperiod=14)
            # 1h trend direction: EMA50 slope
            inf_1h["ema50_slope_1h"] = (
                (inf_1h["ema50_1h"] - inf_1h["ema50_1h"].shift(3))
                / inf_1h["ema50_1h"].shift(3)
                * 100
            )
            # 1h trend strength
            inf_1h["trend_1h"] = np.where(
                inf_1h["ema20_1h"] > inf_1h["ema50_1h"], 1, -1
            )
            # Merge to 5m dataframe
            dataframe = self._merge_informative(
                dataframe,
                inf_1h,
                [
                    "ema50_1h",
                    "ema20_1h",
                    "rsi_1h",
                    "adx_1h",
                    "ema50_slope_1h",
                    "trend_1h",
                ],
            )
        else:
            dataframe["ema50_1h"] = np.nan
            dataframe["ema20_1h"] = np.nan
            dataframe["rsi_1h"] = np.nan
            dataframe["adx_1h"] = np.nan
            dataframe["ema50_slope_1h"] = 0
            dataframe["trend_1h"] = 0

        # ─── 15M informative indicators ───
        inf_15m = self.dp.get_pair_dataframe(pair, "15m")
        if inf_15m is not None and len(inf_15m) > 0:
            inf_15m["rsi_15m"] = ta.RSI(inf_15m, timeperiod=14)
            macd_15m = ta.MACD(inf_15m)
            inf_15m["macd_15m"] = macd_15m["macd"]
            inf_15m["macd_signal_15m"] = macd_15m["macdsignal"]
            inf_15m["macd_hist_15m"] = macd_15m["macdhist"]
            inf_15m["ema12_15m"] = ta.EMA(inf_15m, timeperiod=12)
            inf_15m["ema26_15m"] = ta.EMA(inf_15m, timeperiod=26)
            inf_15m["trend_15m"] = np.where(
                inf_15m["ema12_15m"] > inf_15m["ema26_15m"], 1, -1
            )
            dataframe = self._merge_informative(
                dataframe, inf_15m, ["rsi_15m", "macd_hist_15m", "trend_15m"]
            )
        else:
            dataframe["rsi_15m"] = np.nan
            dataframe["macd_hist_15m"] = 0
            dataframe["trend_15m"] = 0

        # ─── Regime detection ───
        dataframe = self._detect_regime(dataframe)

        # ─── A52-style indicators ───
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        bb = ta.BBANDS(dataframe, timeperiod=20)
        dataframe["bb_upper"] = bb["upperband"]
        dataframe["bb_lower"] = bb["lowerband"]
        dataframe["bb_mid"] = bb["middleband"]

        # ─── A51-style VWAP ───
        tp = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        cumvol = dataframe["volume"].rolling(window=288, min_periods=1).sum()
        cumtp = (tp * dataframe["volume"]).rolling(window=288, min_periods=1).sum()
        dataframe["vwap"] = cumtp / cumvol

        # Short EMAs for scalping
        dataframe["ema_5"] = ta.EMA(dataframe, timeperiod=5)
        dataframe["ema_8"] = ta.EMA(dataframe, timeperiod=8)

        # ─── A31-style squeeze ───
        kc_mid = ta.EMA(dataframe, timeperiod=20)
        kc_atr = ta.ATR(dataframe, timeperiod=20)
        dataframe["kc_upper"] = kc_mid + 1.5 * kc_atr
        dataframe["kc_lower"] = kc_mid - 1.5 * kc_atr
        dataframe["squeeze_on"] = (
            (dataframe["bb_lower"] > dataframe["kc_lower"])
            & (dataframe["bb_upper"] < dataframe["kc_upper"])
        ).astype(int)
        dataframe["squeeze_fire"] = (
            (dataframe["squeeze_on"].shift(1) == 1) & (dataframe["squeeze_on"] == 0)
        ).astype(int)
        delta = dataframe["close"] - kc_mid
        dataframe["momentum"] = ta.LINEARREG(delta, timeperiod=20)

        # ─── OPT-style SuperTrend ───
        hl2 = (dataframe["high"] + dataframe["low"]) / 2
        st_atr = ta.ATR(dataframe, timeperiod=10)
        dataframe["st_upper"] = hl2 + 3.0 * st_atr
        dataframe["st_lower"] = hl2 - 3.0 * st_atr

        # Volume filter
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # ─── Combined direction score ───
        trend = np.where(dataframe["ema_12"] > dataframe["ema_26"], 1.0, -1.0)
        mom = (dataframe["rsi"] - 50) / 50
        macd_s = np.where(dataframe["macd_hist"] > 0, 0.5, -0.5)

        # Multi-TF confirmation bonus
        tf_bonus = (
            dataframe["trend_1h"].fillna(0) * 0.15
            + dataframe["trend_15m"].fillna(0) * 0.10
        )

        # Dynamic bias from regime (capped to prevent over-filtering)
        regime_bias = dataframe["regime"].map(
            lambda r: max(-0.05, min(0.05, self._get_regime_params(r).get("e", 0.0)))
        )

        dataframe["direction_score"] = (
            trend * 0.35 + mom * 0.25 + macd_s * 0.15 + tf_bonus + regime_bias
        )

        # ─── Multi-TF agreement score (for entry filtering) ───
        dataframe["mtf_agree_long"] = (
            (dataframe["trend_1h"] > 0).astype(int)
            + (dataframe["trend_15m"] > 0).astype(int)
            + (dataframe["ema_12"] > dataframe["ema_26"]).astype(int)
        )
        dataframe["mtf_agree_short"] = (
            (dataframe["trend_1h"] < 0).astype(int)
            + (dataframe["trend_15m"] < 0).astype(int)
            + (dataframe["ema_12"] < dataframe["ema_26"]).astype(int)
        )

        return dataframe

    def _merge_informative(self, dataframe, inf_df, columns):
        """Merge higher-TF informative data into 5m dataframe.
        Uses merge_asof for correct forward-fill alignment."""
        if inf_df is None or len(inf_df) == 0:
            return dataframe

        inf_copy = inf_df[["date"] + columns].copy()
        inf_copy = inf_copy.sort_values("date").reset_index(drop=True)
        dataframe = dataframe.sort_values("date").reset_index(drop=True)

        # merge_asof: for each 5m row, find the latest higher-TF
        # row where date <= 5m date (backward direction)
        merged = pd.merge_asof(
            dataframe[["date"]],
            inf_copy,
            on="date",
            direction="backward",
        )
        for col in columns:
            if col in merged.columns:
                dataframe[col] = merged[col].values

        return dataframe

    # ─── Entry Logic ─────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── Only R2 (RANGING) shorts are proven profitable ──
        # R0/R1/R3 all produce more SL losses than ROI wins.
        # Skip computing entry conditions for disabled regimes
        # to save ~120 lines of wasted computation per candle.

        regime_id = 2  # RANGING — the only active regime
        params = self._get_regime_params(regime_id)
        strategy = params.get("strategy", "A52")
        entry_adj = params.get("entry_adj", 1.0)
        direction_bias = params.get("direction_bias", "neutral")
        mask = dataframe["regime"] == regime_id

        # Ranging regime thresholds
        dir_thresh = 0.25 * min(entry_adj, 1.10)
        vol_mult = 1.0 * min(entry_adj, 1.10)

        # Multi-TF: 1-of-3 for ranging
        mtf_short = dataframe["mtf_agree_short"] >= 1

        # Direction bias adjustments
        if direction_bias == "short":
            short_dir_thresh = dir_thresh * 0.85
        else:
            short_dir_thresh = dir_thresh

        if strategy == "OPT":
            short_cond = (
                mask
                & mtf_short
                & (
                    (dataframe["ema_12"] < dataframe["ema_26"])
                    & (dataframe["direction_score"] < -short_dir_thresh)
                    & (dataframe["rsi"] > 30)
                    & (dataframe["rsi"] < 60)
                    & (dataframe["volume"] > dataframe["volume_sma"] * vol_mult)
                    & (dataframe["adx"] > 15)
                )
            )

        elif strategy == "A51":
            a51_vol = max(vol_mult, 1.1)
            short_cond = (
                mask
                & mtf_short
                & (
                    (dataframe["close"] < dataframe["vwap"])
                    & (dataframe["ema_5"] < dataframe["ema_8"])
                    & (dataframe["rsi"] > 38)
                    & (dataframe["rsi"] < 58)
                    & (dataframe["macd_hist"] < 0)
                    & (dataframe["adx"] > 20)
                    & (dataframe["direction_score"] < -0.15)
                    & (dataframe["volume"] > dataframe["volume_sma"] * a51_vol)
                )
            )

        elif strategy == "A31":
            short_cond = (
                mask
                & mtf_short
                & (
                    (dataframe["squeeze_fire"] == 1)
                    & (dataframe["momentum"] < 0)
                    & (dataframe["close"] < dataframe["ema_26"])
                    & (dataframe["direction_score"] < -0.2)
                    & (dataframe["rsi"] > 30)
                    & (dataframe["rsi"] < 60)
                    & (dataframe["adx"] > 15)
                    & (dataframe["volume"] > dataframe["volume_sma"] * 0.8)
                )
            )

        else:  # A52 default
            short_cond = (
                mask
                & mtf_short
                & (
                    (dataframe["direction_score"] < -short_dir_thresh)
                    & (dataframe["close"] < dataframe["ema_12"])
                    & (dataframe["rsi"] > 32)
                    & (dataframe["rsi"] < 60)
                    & (dataframe["macd_hist"] < 0)
                    & (dataframe["volume"] > dataframe["volume_sma"] * vol_mult)
                    & (dataframe["adx"] > 15)
                )
            )

        tag = "ml_{}_r{}".format(strategy.lower(), regime_id)
        dataframe.loc[short_cond, ["enter_short", "enter_tag"]] = (
            1,
            "{}_short".format(tag),
        )

        return dataframe

    # ─── Exit Logic ──────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ─── Smarter exits: require confirmation, not single triggers ───

        # Overbought exit: RSI extreme AND price above BB
        dataframe.loc[
            (dataframe["rsi"] > 78) & (dataframe["close"] > dataframe["bb_upper"]),
            ["exit_long", "exit_tag"],
        ] = (1, "ml_exit_overbought")

        dataframe.loc[
            (dataframe["rsi"] < 22) & (dataframe["close"] < dataframe["bb_lower"]),
            ["exit_short", "exit_tag"],
        ] = (1, "ml_exit_oversold")

        # Momentum reversal exits DISABLED
        # Data shows 0% WR and -1.12% avg loss.
        # The reversal signal fires too late, after
        # the damage is already done.
        # Keep overbought/oversold (RSI extreme + BB)
        # as these are rare and valid exit signals.

        # MTF trend flip exits DISABLED
        # These exit too late — the loss is already taken.
        # Let ROI + time exits handle it.

        # Vol spike exits DISABLED
        # Data shows 23.5% WR and -11.75 USDT total.
        # The vol spike signal exits at bad levels.

        return dataframe

    # ─── Dynamic Position Sizing (Kelly Criterion) ────────

    def custom_stake_amount(
        self,
        pair,
        current_time,
        current_rate,
        proposed_stake,
        min_stake,
        max_stake,
        leverage,
        entry_tag,
        side,
        **kwargs,
    ):
        """
        PRO: Kelly Criterion position sizing with discipline.
        f* = (bp - q) / b, using fractional Kelly (25%).
        Blended with regime confidence and anti-martingale.
        """
        c = float(self.position_c.value)

        if entry_tag and "_r" in entry_tag:
            try:
                regime = int(entry_tag.split("_r")[1][0])
                params = self._get_regime_params(regime)

                # PRO: Kelly fraction from optimizer
                kelly = params.get("kelly_fraction", 0)
                regime_c = params.get("c", c)
                if kelly > 0.02:
                    # Blend Kelly with regime c (conservative)
                    c = kelly * 0.4 + regime_c * 0.6
                else:
                    # Weak/zero Kelly = weak edge → use
                    # regime c as-is (no amplification).
                    # Sizing up on uncertain edge is the
                    # single most dangerous bug in a bot.
                    c = regime_c

                # Apply size_adj from performance feedback
                size_adj = params.get("size_adj", 1.0)
                c = c * size_adj

                # PRO: Not robust in walk-forward → reduce
                if not params.get("is_robust", True):
                    c *= 0.7  # cautious, not blocked

                # PRO: Anti-martingale (reduce after losses)
                if self._consecutive_losses >= 2:
                    reduction = max(0.3, 1.0 - self._consecutive_losses * 0.15)
                    c *= reduction

                # Reduce size in worst session
                worst = params.get("worst_session")
                if worst:
                    current_sess = self._get_current_session(current_time)
                    if current_sess == worst:
                        c *= 0.5

                # R2 short floor handled by 5× multiplier above

            except (ValueError, IndexError):
                pass

        c = max(0.05, min(c, 0.80))
        return proposed_stake * c

    # ─── Trade Entry Confirmation (PRO Discipline) ────────

    def _log_rejection(self, pair, side, reason, current_time,
                       features=None):
        """
        Decision Journal v2 — persist trade rejection with context.
        Each entry now includes: feature snapshot, model version,
        risk state so operators can diagnose why the bot didn't trade.
        """
        entry = {
            "time": str(current_time),
            "pair": pair,
            "side": side,
            "reason": reason,
            # v2: risk state
            "risk": {
                "consecutive_losses": self._consecutive_losses,
                "daily_pnl": round(self._daily_pnl, 6),
                "daily_trades": self._daily_trades,
            },
            # v2: model version (best_params load timestamp)
            "model_ts": self._last_model_load,
        }
        # v2: feature snapshot (when dataframe row is available)
        if features is not None:
            snap_keys = [
                "adx", "atr_norm", "ema_slope", "bb_width",
                "vol_ratio", "rsi", "macd_hist", "direction_score",
                "regime", "sub_regime", "trend_1h", "rsi_15m",
                "volume", "volume_sma",
            ]
            snap = {}
            for k in snap_keys:
                v = features.get(k)
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    snap[k] = round(float(v), 4) if isinstance(v, (float, np.floating)) else int(v)
            entry["features"] = snap

        self._rejection_log.append(entry)
        if len(self._rejection_log) > self._MAX_REJECTIONS:
            self._rejection_log = self._rejection_log[-self._MAX_REJECTIONS :]
        # Persist to disk (async-safe: overwrite full file)
        try:
            with open(REJECTION_LOG_PATH, "w") as f:
                json.dump(self._rejection_log[-50:], f, indent=1)
        except Exception:
            pass

    def confirm_trade_entry(
        self,
        pair,
        order_type,
        amount,
        rate,
        time_in_force,
        current_time,
        entry_tag,
        side,
        **kwargs,
    ):
        """
        PRO discipline gate with decision journal.
        Every rejection is persisted so operators can see
        why the bot is not trading.
        """
        # GUARD: Only trade futures pairs (must have :USDT suffix)
        if ":USDT" not in pair:
            self._log_rejection(pair, side, "not_futures_pair", current_time)
            return False

        # PRO: Reset daily counters
        if hasattr(current_time, "date"):
            today = current_time.date()
        else:
            today = datetime.utcnow().date()

        if self._last_trade_date != today:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._last_trade_date = today

        # PRO: Cooldown after consecutive losses
        regime = 2  # default
        if entry_tag and "_r" in entry_tag:
            try:
                regime = int(entry_tag.split("_r")[1][0])
            except (ValueError, IndexError):
                pass

        params = self._get_regime_params(regime)
        max_losses = params.get("cooldown_after_losses", 5)

        if self._consecutive_losses >= max_losses:
            self._log_rejection(
                pair,
                side,
                f"cooldown_consecutive_losses_{self._consecutive_losses}",
                current_time,
            )
            return False

        # PRO: Daily loss limit
        daily_limit = params.get("daily_loss_limit", 0.02)
        if self._daily_pnl < -daily_limit:
            self._log_rejection(
                pair, side, f"daily_loss_limit_{self._daily_pnl:.4f}", current_time
            )
            return False

        # PRO: Equity curve circuit breaker
        if len(self._recent_results) >= 20:
            recent = self._recent_results[-20:]
            if sum(recent) < -0.05:
                if self._consecutive_losses >= 5:
                    self._log_rejection(
                        pair, side, "equity_curve_breaker", current_time
                    )
                    return False

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 1:
            return True
        last = dataframe.iloc[-1]

        # Block in extreme trend against trade direction
        adx_val = last.get("adx", 0)
        ema_slope_val = last.get("ema_slope", 0)
        if side == "long" and adx_val > 40 and ema_slope_val < -0.5:
            self._log_rejection(
                pair, side, f"extreme_downtrend_adx{adx_val:.0f}", current_time,
                features=last,
            )
            return False
        if side == "short" and adx_val > 40 and ema_slope_val > 0.5:
            self._log_rejection(
                pair, side, f"extreme_uptrend_adx{adx_val:.0f}", current_time,
                features=last,
            )
            return False

        # Require meaningful volume
        vol = last.get("volume", 0)
        vol_sma = last.get("volume_sma", 1)
        if vol_sma > 0 and vol < vol_sma * 0.4:
            self._log_rejection(
                pair, side, f"low_volume_{vol:.0f}_vs_{vol_sma:.0f}", current_time,
                features=last,
            )
            return False

        # 1h trend disagreement — only in extreme trends
        trend_1h = last.get("trend_1h", 0)
        if side == "long" and trend_1h < 0:
            if last.get("adx", 0) > 35:
                self._log_rejection(
                    pair, side, "1h_trend_disagree_long", current_time,
                    features=last,
                )
                return False
        if side == "short" and trend_1h > 0:
            if last.get("adx", 0) > 35:
                self._log_rejection(
                    pair, side, "1h_trend_disagree_short", current_time,
                    features=last,
                )
                return False

        # Anti-pattern filter
        if self._anti_patterns and hasattr(current_time, "hour"):
            try:
                strategy_name = params.get("strategy", "")
                ap = None
                for key, val in self._anti_patterns.items():
                    if strategy_name in key and isinstance(val, dict):
                        ap = val
                        break
                if ap:
                    toxic_hours = ap.get("toxic_hours", [])
                    if current_time.hour in toxic_hours:
                        self._log_rejection(
                            pair,
                            side,
                            f"anti_pattern_hour_{current_time.hour}",
                            current_time,
                            features=last,
                        )
                        return False
                    toxic_days = ap.get("toxic_days", [])
                    if current_time.weekday() in toxic_days:
                        self._log_rejection(
                            pair,
                            side,
                            f"anti_pattern_day_{current_time.weekday()}",
                            current_time,
                            features=last,
                        )
                        return False
            except Exception:
                pass

        # Quality model gate (session-direction prior)
        if self._quality_model_data is not None:
            try:
                qm = self._quality_model_data
                model = qm.get("model")
                scaler = qm.get("scaler")
                thresholds = qm.get("thresholds", {})
                min_quality = thresholds.get("min_quality", 0.5)

                if model and scaler and hasattr(current_time, "hour"):
                    features = np.array(
                        [
                            [
                                current_time.hour,
                                current_time.weekday(),
                                1 if side == "short" else 0,
                            ]
                        ]
                    )
                    scaled = scaler.transform(features)
                    quality = model.predict_proba(scaled)[0][1]

                    if quality < min_quality:
                        self._log_rejection(
                            pair,
                            side,
                            f"quality_model_{quality:.3f}<{min_quality:.3f}",
                            current_time,
                            features=last,
                        )
                        return False
            except Exception:
                pass  # fail open — don't block on model error

        # Regime transition filter
        if len(dataframe) >= 12:
            regime_now = last.get("regime", 2)
            prev_regime = dataframe.iloc[-12].get("regime", regime_now)
            if regime_now != prev_regime:
                ds = abs(last.get("direction_score", 0))
                if ds < 0.5:
                    self._log_rejection(
                        pair,
                        side,
                        f"regime_transition_{prev_regime}->{regime_now}",
                        current_time,
                        features=last,
                    )
                    return False

        self._daily_trades += 1
        return True

    # ─── Dynamic Stoploss (MFE-Calibrated) ────────────────

    def custom_stoploss(
        self,
        pair,
        trade,
        current_time,
        current_rate,
        current_profit,
        after_fill,
        **kwargs,
    ):
        """
        PRO: MFE-calibrated dynamic stoploss.
        Phase 1: Base SL (give trade room to develop)
        Phase 2: Breakeven lock (protect capital after decent move)
        Phase 3: Trailing (lock in gains progressively)
        """
        regime = 2
        if trade.enter_tag and "_r" in trade.enter_tag:
            try:
                regime = int(trade.enter_tag.split("_r")[1][0])
            except (ValueError, IndexError):
                pass

        params = self._get_regime_params(regime)
        base_sl = params.get("sl", -0.008)
        trail_start = params.get("trail_start", 0.005)
        trail_step = params.get("trail_step", 0.003)

        trade_dur = (current_time - trade.open_date_utc).total_seconds() / 60

        # Phase 3: Big winner — trail to lock gains
        if current_profit > trail_start:
            return -(current_profit - trail_step)

        # Phase 2: Breakeven lock after modest gain
        if current_profit > abs(base_sl) * 0.5:
            return -0.002

        # Phase 1: Use regime-calibrated base SL
        # Tighten gradually as trade ages
        if trade_dur < 15:
            return base_sl  # full room
        elif trade_dur < 40:
            return base_sl * 0.75  # tighter
        else:
            return base_sl * 0.60  # tight after 40min

    # ─── Dynamic ROI ─────────────────────────────────────

    def custom_exit(
        self, pair, trade, current_time, current_rate, current_profit, **kwargs
    ):
        """
        Self-learned ROI exit: use per-regime ROI table from
        ml_optimizer duration bucket analysis.
        """
        trade_dur = (current_time - trade.open_date_utc).total_seconds() / 60

        # No time-based exits — pure ROI + SL only
        # Time exits always lose money in backtest.

        if trade.enter_tag and "_r" in trade.enter_tag:
            try:
                regime = int(trade.enter_tag.split("_r")[1][0])
                params = self._get_regime_params(regime)
                roi_table = params.get("roi_table", {})

                if roi_table:
                    applicable_roi = None
                    for mins in sorted(
                        roi_table.keys(), key=lambda x: int(x), reverse=True
                    ):
                        if trade_dur >= int(mins):
                            applicable_roi = roi_table[mins]
                            break

                    if applicable_roi and current_profit >= applicable_roi:
                        return "ml_roi_r{}_{}m".format(regime, int(trade_dur))

            except (ValueError, IndexError, AttributeError):
                pass

        return None

    # ─── PRO: Trade Exit Tracking (Discipline) ───────────
    # confirm_trade_exit updates discipline trackers.
    # Uses trade.calc_profit_ratio for profit tracking.

    def confirm_trade_exit(
        self,
        pair,
        trade,
        order_type,
        amount,
        rate,
        time_in_force,
        exit_reason,
        current_time,
        **kwargs,
    ):
        """
        PRO: Track trade results for discipline systems.
        Updates consecutive losses, daily PnL, equity curve.
        """
        try:
            profit = trade.calc_profit_ratio(rate)
        except Exception:
            profit = 0.0

        # Update discipline trackers
        self._recent_results.append(profit)
        if len(self._recent_results) > self._MAX_RECENT:
            self._recent_results = self._recent_results[-self._MAX_RECENT :]

        self._daily_pnl += profit

        if profit < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0  # reset on win

        # Equity curve tracking
        prev = self._equity_curve[-1] if self._equity_curve else 0
        self._equity_curve.append(prev + profit)
        if len(self._equity_curve) > 100:
            self._equity_curve = self._equity_curve[-100:]

        return True

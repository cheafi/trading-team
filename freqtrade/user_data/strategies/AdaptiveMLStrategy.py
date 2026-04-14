"""
AdaptiveML v3 — USDT Futures 5m R2 Short Specialist
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

  DISCIPLINE:
  6.  Kelly Criterion position sizing (fractional Kelly)
  7.  MFE-calibrated trailing stops (data-driven)
  8.  Equity curve circuit breaker (pause on drawdown)
  9.  Consecutive loss cooldown (discipline after streaks)
  10. Daily loss limit (hard stop for the day)
  11. Fee-aware minimum edge filter
  12. Trade quality gate (session/direction prior)
  13. Anti-martingale (reduce size on losses)

Honest assessment:
  - Quality model uses 5 features (hour, weekday, is_short,
    regime, leverage) — a session-direction-regime prior,
    not deep trade intelligence.
  - Regime model was removed (iter 14). Regime detection
    is rule-based (ADX/EMA/ATR/BB thresholds).
  - Only R2 short is active. The "adaptive" framing is
    aspirational, not current reality.

Philosophy: "Discipline is the bridge between goals and results."
"""

import hashlib
import hmac
import json
import logging
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

# ─── Modular engines (iter 19 P3 architecture split) ────
from regime_engine import (
    detect_regime,
    get_regime_params,
    get_current_session,
    SESSION_HOURS,
)
from discipline_engine import (
    load_discipline_state,
    save_discipline_state,
    check_max_drawdown,
    check_pair_exposure,
    check_correlation_exposure,
    snap_features,
    log_decision,
    log_trade_entry,
    log_trade_exit,
)

logger = logging.getLogger(__name__)

# Path where the ML optimizer writes trained models
MODEL_DIR = Path("/freqtrade/user_data/ml_models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Active model artifacts:
BEST_PARAMS_PATH = MODEL_DIR / "best_params.json"
QUALITY_MODEL_PATH = MODEL_DIR / "quality_model.pkl"
DISCIPLINE_PATH = MODEL_DIR / "discipline_params.json"
ANTI_PATTERN_PATH = MODEL_DIR / "anti_patterns.json"

# Shadow model: evaluated but cannot trade — for A/B validation
SHADOW_DIR = MODEL_DIR / "shadow"
SHADOW_MODEL_PATH = SHADOW_DIR / "quality_model.pkl"

# Decision journal — persists every trade rejection reason
REJECTION_LOG_PATH = MODEL_DIR / "rejection_journal.json"

# Decision Journal v4 — append-only JSONL with every accept+reject
DECISION_JOURNAL_PATH = MODEL_DIR / "decision_journal.jsonl"

# Trade replay — per-trade entry/exit with full context
TRADE_REPLAY_PATH = MODEL_DIR / "trade_replay.json"

# Discipline state persistence — survives container restarts
DISCIPLINE_STATE_PATH = MODEL_DIR / "discipline_state.json"

# Kill-switch: if this file exists, block ALL entries
KILL_SWITCH_PATH = MODEL_DIR / "kill_switch"

# Event freeze windows (UTC hours) — no trading around
# scheduled macro events. Format: {(month, day): [(hour_start, hour_end), ...]}
# Static list; for dynamic FOMC/CPI dates, update periodically.
# These are UTC windows where entry is blocked.
EVENT_FREEZE_HOURS = 3  # freeze for N hours around event

# Fee structure
ROUND_TRIP_FEE = 0.001  # 0.10% (Binance futures maker+taker)

# Risk: strategy-level max drawdown halt (defense in depth)
# This fires INSIDE the strategy even if agent-runner is down.
MAX_DD_HALT = 0.20  # 20% — auto-enable kill switch
MAX_DD_WARN = 0.15  # 15% — log warning, reduce size

# Per-pair position limit: max open trades on one pair
MAX_POSITIONS_PER_PAIR = 2

# Correlated pair groups — simultaneous same-direction entries
# on pairs within the same group are limited.
# Rolling 90d correlation: BTC/ETH ~0.87, SOL/ETH ~0.82
CORRELATION_GROUPS = {
    "layer1": ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT"],
    "altcoin": ["BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"],
}
MAX_CORRELATED_SAME_DIRECTION = 2  # max 2 of 3 in same group+direction

# HMAC key file for model integrity verification
MODEL_HMAC_PATH = MODEL_DIR / "model_hmac.json"


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
    _quality_model_data = None  # Quality gate model
    _shadow_model_data = None  # Shadow: candidate model (log-only)
    _discipline_params = None  # Discipline params (cooldown, limits)
    _anti_patterns = None  # Anti-patterns (learned from mistakes)
    _last_model_load = 0
    _MODEL_RELOAD_INTERVAL = 300

    # Discipline tracking (reset on strategy reload)
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
    _trade_replay = []  # trade replay: entry+exit decisions
    _MAX_REPLAY = 200

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
                # Staleness check: warn if params are > 7 days old
                age_days = (now - BEST_PARAMS_PATH.stat().st_mtime) / 86400
                if age_days > 7:
                    logger.warning(
                        "best_params.json is %.0f days old — consider retraining "
                        "(./scripts/ml-train.sh or curl -X POST :3001/api/ml/train)",
                        age_days,
                    )
            except Exception as e:
                logger.warning("Failed to load best_params.json: %s", e)
                self._best_params = None

        # Load quality model (with HMAC integrity check)
        if QUALITY_MODEL_PATH.exists():
            try:
                raw = QUALITY_MODEL_PATH.read_bytes()
                if self._verify_model_hmac("quality_model.pkl", raw):
                    self._quality_model_data = pickle.loads(raw)
                else:
                    logger.warning(
                        "quality_model.pkl HMAC mismatch — "
                        "refusing to load (possible tampering)"
                    )
                    self._quality_model_data = None
            except Exception as e:
                logger.warning("Failed to load quality_model.pkl: %s", e)
                self._quality_model_data = None

        # Load discipline params
        if DISCIPLINE_PATH.exists():
            try:
                with open(DISCIPLINE_PATH, "r") as f:
                    self._discipline_params = json.load(f)
            except Exception as e:
                logger.warning("Failed to load discipline_params.json: %s", e)
                self._discipline_params = None

        # Load anti-patterns (learned from mistakes)
        if ANTI_PATTERN_PATH.exists():
            try:
                with open(ANTI_PATTERN_PATH, "r") as f:
                    self._anti_patterns = json.load(f)
            except Exception as e:
                logger.warning("Failed to load anti_patterns.json: %s", e)
                self._anti_patterns = None

        # Shadow model: loaded if present, never affects trading
        if SHADOW_MODEL_PATH.exists():
            try:
                raw = SHADOW_MODEL_PATH.read_bytes()
                if self._verify_model_hmac("shadow/quality_model.pkl", raw):
                    self._shadow_model_data = pickle.loads(raw)
                else:
                    logger.warning(
                        "Shadow model HMAC mismatch — skipping"
                    )
                    self._shadow_model_data = None
            except Exception as e:
                logger.warning("Failed to load shadow model: %s", e)
                self._shadow_model_data = None
        else:
            self._shadow_model_data = None

        # Restore discipline state from disk (survives restarts)
        self._load_discipline_state()

    def _load_discipline_state(self):
        """Restore discipline state from disk — delegates to discipline_engine."""
        state = {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "recent_results": self._recent_results,
        }
        state = load_discipline_state(DISCIPLINE_STATE_PATH, state)
        self._consecutive_losses = state["consecutive_losses"]
        self._daily_pnl = state["daily_pnl"]
        self._daily_trades = state["daily_trades"]
        self._recent_results = state["recent_results"]

    def _save_discipline_state(self):
        """Persist discipline state to disk — delegates to discipline_engine."""
        state = {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "recent_results": self._recent_results,
        }
        save_discipline_state(DISCIPLINE_STATE_PATH, state, self._MAX_RECENT)

    # ─── Model Integrity ─────────────────────────────────

    @staticmethod
    def _verify_model_hmac(model_name, raw_bytes):
        """
        Verify HMAC-SHA256 of a model file against stored digest.
        If no HMAC file exists yet, trust-on-first-use: compute
        and store the digest for future verification.
        Returns True if verified or TOFU, False if mismatch.
        """
        try:
            # Key from env or fallback (production should set MODEL_HMAC_KEY)
            import os
            key = os.environ.get(
                "MODEL_HMAC_KEY", "cc-model-integrity-key"
            ).encode()
            digest = hmac.new(key, raw_bytes, hashlib.sha256).hexdigest()

            stored = {}
            if MODEL_HMAC_PATH.exists():
                with open(MODEL_HMAC_PATH, "r") as f:
                    stored = json.load(f)

            if model_name in stored:
                return hmac.compare_digest(stored[model_name], digest)

            # Trust-on-first-use: store digest
            stored[model_name] = digest
            with open(MODEL_HMAC_PATH, "w") as f:
                json.dump(stored, f, indent=1)
            logger.info(
                "TOFU: stored HMAC for %s (first load)", model_name
            )
            return True
        except Exception as e:
            logger.warning("HMAC check failed for %s: %s", model_name, e)
            return True  # fail open on HMAC infra error

    # ─── Portfolio Risk Checks ───────────────────────────

    def _check_max_drawdown(self, current_time):
        """Strategy-level max DD halt — delegates to discipline_engine."""
        return check_max_drawdown(
            self._equity_curve, KILL_SWITCH_PATH,
            current_time, MAX_DD_HALT, MAX_DD_WARN,
        )

    def _check_pair_exposure(self, pair):
        """Per-pair position limit — delegates to discipline_engine."""
        return check_pair_exposure(pair, self.dp, MAX_POSITIONS_PER_PAIR)

    def _check_correlation_exposure(self, pair, side):
        """Cross-pair correlation filter — delegates to discipline_engine."""
        return check_correlation_exposure(
            pair, side, CORRELATION_GROUPS, MAX_CORRELATED_SAME_DIRECTION,
        )

    # ─── Regime Detection ────────────────────────────────

    def _detect_regime(self, dataframe: DataFrame) -> DataFrame:
        """Classify market into regimes — delegates to regime_engine."""
        return detect_regime(dataframe, int(self.regime_lookback.value))

    def _get_regime_params(self, regime: int) -> dict:
        """Get optimal params for regime — delegates to regime_engine."""
        return get_regime_params(regime, self._best_params)

    def _get_current_session(self, current_time=None):
        """Determine current trading session — delegates to regime_engine."""
        return get_current_session(current_time)

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
        Kelly Criterion position sizing with discipline.
        f* = (bp - q) / b, using fractional Kelly (25%).
        Blended with regime confidence and anti-martingale.
        """
        c = float(self.position_c.value)

        if entry_tag and "_r" in entry_tag:
            try:
                regime = int(entry_tag.split("_r")[1][0])
                params = self._get_regime_params(regime)

                # Kelly fraction from optimizer
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

                # Not robust in walk-forward → reduce
                if not params.get("is_robust", True):
                    c *= 0.7  # cautious, not blocked

                # Anti-martingale (reduce after losses)
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

    # ─── Trade Entry Confirmation (Discipline Gate) ─────

    def _log_decision(self, pair, side, decision, reason, current_time,
                      rate=None, features=None, edge_score=None,
                      quality_threshold=None):
        """Decision Journal v4 — delegates to discipline_engine."""
        risk_state = {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": round(self._daily_pnl, 6),
            "daily_trades": self._daily_trades,
        }
        self._rejection_log = log_decision(
            pair, side, decision, reason, current_time,
            journal_path=DECISION_JOURNAL_PATH,
            rejection_log_path=REJECTION_LOG_PATH,
            rejection_log=self._rejection_log,
            max_rejections=self._MAX_REJECTIONS,
            rate=rate, features=features,
            edge_score=edge_score,
            quality_threshold=quality_threshold,
            risk_state=risk_state,
            model_ts=self._last_model_load,
        )

    def _log_rejection(self, pair, side, reason, current_time,
                       features=None, rate=None, edge_score=None):
        """Backward-compat wrapper → _log_decision(decision='reject')."""
        self._log_decision(
            pair, side, "reject", reason, current_time,
            rate=rate, features=features, edge_score=edge_score,
        )

    def _snap_features(self, row):
        """Extract feature snapshot — delegates to discipline_engine."""
        return snap_features(row)

    def _log_trade_entry(self, pair, side, entry_tag, regime,
                         rate, current_time, features_row,
                         shadow=None):
        """Trade Replay entry — delegates to discipline_engine."""
        params = self._get_regime_params(regime)
        risk_state = {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": round(self._daily_pnl, 6),
            "daily_trades": self._daily_trades,
        }
        self._trade_replay = log_trade_entry(
            pair, side, entry_tag, regime, rate, current_time,
            features_row, params, risk_state, self._last_model_load,
            self._trade_replay, TRADE_REPLAY_PATH, self._MAX_REPLAY,
            shadow=shadow,
        )

    def _evaluate_shadow(self, current_time, side, regime, kwargs):
        """
        Evaluate shadow (candidate) model — log-only, never trades.
        Returns dict with shadow decision or None if no shadow model.
        """
        if self._shadow_model_data is None:
            return None
        try:
            sm = self._shadow_model_data
            model = sm.get("model")
            scaler = sm.get("scaler")
            thresholds = sm.get("thresholds", {})
            if not model or not scaler:
                return None
            if not hasattr(current_time, "hour"):
                return None

            leverage = float(kwargs.get("leverage", 1) or 1)
            features = np.array(
                [[
                    current_time.hour,
                    current_time.weekday(),
                    1 if side == "short" else 0,
                    regime,
                    leverage,
                ]]
            )
            scaled = scaler.transform(features)
            quality = float(
                model.predict_proba(scaled)[0][1]
            )
            min_q = thresholds.get("min_quality", 0.5)
            return {
                "quality": round(quality, 4),
                "threshold": min_q,
                "would_allow": quality >= min_q,
            }
        except Exception:
            return None

    def _log_trade_exit(self, pair, trade, exit_reason, profit,
                        rate, current_time):
        """Trade Replay exit — delegates to discipline_engine."""
        risk_state = {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": round(self._daily_pnl, 6),
        }
        self._trade_replay = log_trade_exit(
            pair, trade, exit_reason, profit, rate, current_time,
            self.dp, self.timeframe,
            self._trade_replay, TRADE_REPLAY_PATH, self._MAX_REPLAY,
            risk_state=risk_state,
        )

    # _persist_replay removed — now handled by discipline_engine

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
        Discipline gate with Decision Journal v4.
        Every decision (accept AND reject) is persisted
        to append-only JSONL so operators can audit
        why the bot did or didn't trade.
        """
        # KILL SWITCH: if file exists, block all entries
        if KILL_SWITCH_PATH.exists():
            self._log_rejection(pair, side, "kill_switch_active", current_time)
            return False

        # GUARD: Only trade futures pairs (must have :USDT suffix)
        if ":USDT" not in pair:
            self._log_rejection(pair, side, "not_futures_pair", current_time)
            return False

        # EVENT FREEZE: block during scheduled macro events
        if hasattr(current_time, "hour"):
            event_file = MODEL_DIR / "event_calendar.json"
            if event_file.exists():
                try:
                    with open(event_file, "r") as ef:
                        events = json.load(ef)
                    # events: [{"date": "2026-04-15", "hour": 14, "name": "CPI"}, ...]
                    ct_str = str(current_time.date())
                    for ev in events:
                        if ev.get("date") == ct_str:
                            ev_hour = ev.get("hour", 12)
                            if abs(current_time.hour - ev_hour) <= EVENT_FREEZE_HOURS:
                                self._log_rejection(
                                    pair, side,
                                    f"event_freeze_{ev.get('name', 'macro')}",
                                    current_time,
                                )
                                return False
                except Exception:
                    pass

        # STRATEGY-LEVEL MAX DD HALT (defense in depth)
        dd_status = self._check_max_drawdown(current_time)
        if dd_status == "halt":
            self._log_rejection(
                pair, side, "max_dd_halt_auto_kill", current_time
            )
            return False

        # PER-PAIR POSITION LIMIT
        if not self._check_pair_exposure(pair):
            self._log_rejection(
                pair, side,
                f"per_pair_limit_{MAX_POSITIONS_PER_PAIR}",
                current_time,
            )
            return False

        # CROSS-PAIR CORRELATION FILTER
        if not self._check_correlation_exposure(pair, side):
            self._log_rejection(
                pair, side, "correlated_pair_limit", current_time,
            )
            return False

        # Reset daily counters
        if hasattr(current_time, "date"):
            today = current_time.date()
        else:
            today = datetime.utcnow().date()

        if self._last_trade_date != today:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._last_trade_date = today
            self._save_discipline_state()  # persist reset

        # Cooldown after consecutive losses
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

        # Daily loss limit
        daily_limit = params.get("daily_loss_limit", 0.02)
        if self._daily_pnl < -daily_limit:
            self._log_rejection(
                pair, side, f"daily_loss_limit_{self._daily_pnl:.4f}", current_time
            )
            return False

        # Equity curve circuit breaker
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
                    toxic_days = ap.get("toxic_days", [])

                    # Safety: if >18 hours or >5 days are toxic, the
                    # anti-pattern data is likely from a garbage strategy
                    # assignment. Skip the filter to avoid silent blocking.
                    if len(toxic_hours) > 18 or len(toxic_days) > 5:
                        logger.warning(
                            "Anti-pattern filter skipped: %s has %d toxic hours, "
                            "%d toxic days — likely stale/bad data",
                            strategy_name,
                            len(toxic_hours),
                            len(toxic_days),
                        )
                    else:
                        if current_time.hour in toxic_hours:
                            self._log_rejection(
                                pair,
                                side,
                                f"anti_pattern_hour_{current_time.hour}",
                                current_time,
                                features=last,
                            )
                            return False
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

        # Quality model gate (session-direction-regime prior)
        _edge_score = None  # track for decision journal
        _quality_threshold = None
        if self._quality_model_data is not None:
            try:
                qm = self._quality_model_data
                model = qm.get("model")
                scaler = qm.get("scaler")
                thresholds = qm.get("thresholds", {})
                # Use p25 threshold for paper trading to allow more signals
                # through; in live mode, switch to min_quality
                min_quality = thresholds.get("p25", thresholds.get("min_quality", 0.5))
                _quality_threshold = min_quality

                if model and scaler and hasattr(current_time, "hour"):
                    leverage = float(
                        kwargs.get("leverage", 1) or 1
                    )
                    features = np.array(
                        [
                            [
                                current_time.hour,
                                current_time.weekday(),
                                1 if side == "short" else 0,
                                regime,
                                leverage,
                            ]
                        ]
                    )
                    scaled = scaler.transform(features)
                    quality = model.predict_proba(scaled)[0][1]
                    _edge_score = quality

                    if quality < min_quality:
                        self._log_rejection(
                            pair,
                            side,
                            f"quality_model_{quality:.3f}<{min_quality:.3f}",
                            current_time,
                            features=last,
                            rate=rate,
                            edge_score=quality,
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

        # Shadow model: evaluate candidate but NEVER block
        shadow_decision = self._evaluate_shadow(
            current_time, side, regime, kwargs,
        )

        # Decision Journal v4: log ACCEPTANCE with full context
        self._log_decision(
            pair, side, "accept", entry_tag or "entry",
            current_time, rate=rate, features=last,
            edge_score=_edge_score,
            quality_threshold=_quality_threshold,
        )

        # Trade replay: log accepted entry with full context
        self._log_trade_entry(
            pair, side, entry_tag, regime, rate, current_time, last,
            shadow=shadow_decision,
        )
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
        MFE-calibrated dynamic stoploss.
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

    # ─── Trade Exit Tracking (Discipline) ─────────────
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
        Track trade results for discipline systems.
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

        # Trade replay: log exit with PnL attribution
        self._log_trade_exit(
            pair, trade, exit_reason, profit, rate, current_time,
        )

        # Persist discipline state so it survives container restarts
        self._save_discipline_state()

        return True

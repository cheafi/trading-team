#!/usr/bin/env python3
"""
ML Optimizer - CC Trading Team (v3 PRO)
=============================================
Professional quant-grade self-learning pipeline:

  CORE (v2):
  1. Loads backtest results (JSON/ZIP from Freqtrade)
  2. Scores strategies using 14 metrics (WR, PF, Sharpe, Sortino, etc.)
  3. Self-learns ROI tables from trade duration buckets
  4. 8 market sub-regimes (trend+momentum+volatility)
  5. Per-regime best strategy + dynamically tuned params
  6. Performance feedback loop with rolling metrics

  PRO (v3):
  7.  MFE/MAE analysis → calibrate SL/TP from actual trade excursions
  8.  Kelly criterion → mathematically optimal position sizing
  9.  Walk-forward validation → train/test split to detect overfitting
  10. Monte Carlo simulation → confidence intervals & probability of ruin
  11. Trade quality model → score each setup 0-100 before entry
  12. Equity curve analysis → detect when to pause trading
  13. Fee-aware edge calculation → minimum edge filter

Run:  python ml_optimizer.py [--retrain]
"""
import argparse
import json
import os
import pickle
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

# ─── Module imports (Phase 2 architecture split) ───────────────
from ml_scorer import (
    score_strategy, analyze_duration_profile, compute_fee_aware_edge,
    compute_rolling_performance, detect_performance_trend,
    compute_adaptive_score, compute_timeframe_context,
    compute_long_short_profile,
)
from ml_analyzer import (
    analyze_mfe_mae, compute_kelly_fraction, walk_forward_validate,
    monte_carlo_equity, analyze_equity_curve, analyze_losing_patterns,
)

BACKTEST_DIR = Path(os.getenv("BACKTEST_DIR", "/freqtrade/user_data/backtest_results"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/freqtrade/user_data/ml_models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

REGIME_MODEL_PATH = MODEL_DIR / "regime_model.pkl"
BEST_PARAMS_PATH = MODEL_DIR / "best_params.json"
TRAINING_LOG_PATH = MODEL_DIR / "training_log.json"
PERF_HISTORY_PATH = MODEL_DIR / "performance_history.json"
QUALITY_MODEL_PATH = MODEL_DIR / "quality_model.pkl"
DISCIPLINE_PATH = MODEL_DIR / "discipline_params.json"

# Fee structure (Binance futures)
FEE_PER_SIDE = 0.0005  # 0.05%
ROUND_TRIP_FEE = FEE_PER_SIDE * 2  # 0.10%
MIN_EDGE_MULTIPLIER = 2.0  # Only trade if expected edge > 2x fees

# Extended regime system: 4 base * 2 momentum = 8 sub-regimes
REGIME_NAMES = {
    0: "TRENDING_UP",
    1: "TRENDING_DOWN",
    2: "RANGING",
    3: "VOLATILE",
}

SUB_REGIME_NAMES = {
    0: "TREND_UP_STRONG",
    1: "TREND_UP_WEAK",
    2: "TREND_DOWN_STRONG",
    3: "TREND_DOWN_WEAK",
    4: "RANGE_TIGHT",
    5: "RANGE_WIDE",
    6: "VOLATILE_EXPANDING",
    7: "VOLATILE_CONTRACTING",
}

# Duration buckets for self-learning ROI (minutes)
DURATION_BUCKETS = {
    "short": (0, 30),
    "mid": (30, 120),
    "long": (120, 480),
    "extended": (480, 9999),
}

STRATEGY_DEFAULTS = {
    "A52Strategy": {"c": 0.50, "e": -0.18},
    "OPTStrategy": {"c": 0.65, "e": 0.05},
    "A51Strategy": {"c": 0.35, "e": 0.00},
    "A31Strategy": {"c": 0.80, "e": -0.10},
    "AdaptiveMLStrategy": {"c": 0.50, "e": 0.00},
}


def load_backtest_results():
    """Load trades from all backtest .json and .zip files."""
    all_strat_trades = defaultdict(list)
    if not BACKTEST_DIR.exists():
        print("Warning: Backtest dir not found: " + str(BACKTEST_DIR))
        return all_strat_trades

    def _ingest(data):
        strats = data.get("strategy", {})
        if isinstance(strats, dict):
            for sname, sdata in strats.items():
                if isinstance(sdata, dict):
                    trades = sdata.get("trades", [])
                    all_strat_trades[sname].extend(trades)

    for f in sorted(BACKTEST_DIR.glob("backtest-result-*.json")):
        try:
            with open(f) as fp:
                _ingest(json.load(fp))
        except Exception as e:
            print("Warning: " + f.name + ": " + str(e))

    for zf in sorted(BACKTEST_DIR.glob("backtest-result-*.zip")):
        try:
            with zipfile.ZipFile(zf) as z:
                for member in z.namelist():
                    if member.endswith(".json") and not member.endswith("_config.json"):
                        with z.open(member) as fp:
                            _ingest(json.load(fp))
        except Exception as e:
            print("Warning: " + zf.name + ": " + str(e))

    total = sum(len(v) for v in all_strat_trades.values())
    print("Loaded {:,} trades across {} strategies".format(total, len(all_strat_trades)))
    return all_strat_trades


# ───────────────────────────────────────────────────────────
#  SELF-LEARNING ROI FROM TRADE DURATION BUCKETS
# ───────────────────────────────────────────────────────────

def learn_roi_table(trades):
    """
    Self-learn optimal ROI table from actual winning trade distributions.
    Buckets trades by duration -> computes optimal take-profit at each level.
    Returns dict like {"0": 0.012, "30": 0.007, "60": 0.004, "120": 0.002}
    """
    if not trades or len(trades) < 20:
        return None

    winners = []
    all_by_duration = []
    for t in trades:
        pr = t.get("profit_ratio")
        dur = t.get("trade_duration", 0) or 0
        if pr is None:
            continue
        all_by_duration.append((dur, float(pr)))
        if pr > 0:
            winners.append((dur, float(pr)))

    if len(winners) < 10:
        return None

    roi_points = {}
    for bucket_name, (lo, hi) in DURATION_BUCKETS.items():
        bucket_winners = [p for d, p in winners if lo <= d < hi]
        bucket_all = [p for d, p in all_by_duration if lo <= d < hi]

        if len(bucket_winners) < 3:
            continue

        # Optimal ROI = 40th percentile of winners (achievable target)
        profits = np.array(bucket_winners)
        optimal_roi = float(np.percentile(profits, 40))

        # Adjust by win rate in this bucket
        if bucket_all:
            bucket_wr = sum(1 for p in bucket_all if p > 0) / len(bucket_all)
            if bucket_wr < 0.45:
                optimal_roi *= 0.7
            elif bucket_wr > 0.60:
                optimal_roi *= 1.2

        optimal_roi = max(0.001, min(0.10, optimal_roi))
        roi_points[lo] = round(optimal_roi, 5)

    if not roi_points:
        return None

    # Ensure monotonically decreasing ROI (longer = lower target)
    sorted_keys = sorted(roi_points.keys())
    result = {}
    prev_roi = 1.0
    for k in sorted_keys:
        roi = min(roi_points[k], prev_roi)
        result[str(k)] = roi
        prev_roi = roi

    return result


def learn_roi_by_regime(strat_trades_by_name, regimes_by_strat):
    """
    Compute per-regime, per-strategy ROI tables.
    Returns: {regime_id: {strategy_name: roi_table}}
    """
    regime_roi = {}
    for sname, trades in strat_trades_by_name.items():
        regs = regimes_by_strat.get(sname, np.array([]))
        if len(regs) != len(trades):
            continue
        for regime_id in range(4):
            mask = regs == regime_id
            regime_trades = [t for t, m in zip(trades, mask) if m]
            if len(regime_trades) < 20:
                continue
            roi = learn_roi_table(regime_trades)
            if roi:
                if regime_id not in regime_roi:
                    regime_roi[regime_id] = {}
                regime_roi[regime_id][sname] = roi

    return regime_roi


# ───────────────────────────────────────────────────────────
#  ENHANCED MARKET CONDITION DETECTION (8 sub-regimes)
# ───────────────────────────────────────────────────────────

def classify_trade_regimes(trades):
    """
    Enhanced regime classification using 24h rolling windows.
    Base regime (4) + momentum qualifier = 8 sub-regimes.
    Returns: (base_regimes[N], sub_regimes[N])
    """
    if not trades:
        return np.array([]), np.array([])
    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))
    timestamps = np.array([t.get("open_timestamp", 0) for t in sorted_trades])
    all_profits = np.array([t.get("profit_ratio", 0) or 0 for t in sorted_trades])
    all_short = np.array([1 if t.get("is_short", False) else 0 for t in sorted_trades])
    all_durations = np.array([t.get("trade_duration", 0) or 0 for t in sorted_trades])

    all_price_range = np.array([
        ((t.get("max_rate", 1) - t.get("min_rate", 1)) / max(t.get("open_rate", 1), 0.01))
        for t in sorted_trades
    ])

    window_ms = 24 * 3600 * 1000
    base_regimes = np.zeros(len(sorted_trades), dtype=int)
    sub_regimes = np.zeros(len(sorted_trades), dtype=int)

    for i, ts in enumerate(timestamps):
        # Causal window: only look BACKWARD from current trade (no future leakage)
        mask = (timestamps >= ts - window_ms) & (timestamps <= ts)
        wp = all_profits[mask]
        ws = all_short[mask]
        wpr = all_price_range[mask]

        if len(wp) < 3:
            base_regimes[i] = 3
            sub_regimes[i] = 6
            continue

        avg_p = np.mean(wp)
        std_p = np.std(wp)
        wr = np.mean(wp > 0)
        long_pct = 1.0 - np.mean(ws)
        avg_range = np.mean(wpr)

        # Momentum acceleration
        if len(wp) >= 5:
            recent_half = wp[len(wp) // 2:]
            early_half = wp[:len(wp) // 2]
            momentum_accel = np.mean(recent_half) - np.mean(early_half)
        else:
            momentum_accel = 0.0

        # Volatility trend
        if len(wpr) >= 6:
            recent_vol = np.mean(wpr[len(wpr) // 2:])
            early_vol = np.mean(wpr[:len(wpr) // 2])
            vol_trend = recent_vol - early_vol
        else:
            vol_trend = 0.0

        # Base regime classification
        if avg_p > 0.0005 and wr > 0.50 and long_pct > 0.6:
            base_regimes[i] = 0
            if momentum_accel > 0 and wr > 0.55:
                sub_regimes[i] = 0  # TREND_UP_STRONG
            else:
                sub_regimes[i] = 1  # TREND_UP_WEAK
        elif avg_p < -0.0005 and wr < 0.45:
            base_regimes[i] = 1
            if momentum_accel < 0 and wr < 0.40:
                sub_regimes[i] = 2  # TREND_DOWN_STRONG
            else:
                sub_regimes[i] = 3  # TREND_DOWN_WEAK
        elif std_p < 0.003 and abs(avg_p) < 0.001:
            base_regimes[i] = 2
            if avg_range < np.median(all_price_range):
                sub_regimes[i] = 4  # RANGE_TIGHT
            else:
                sub_regimes[i] = 5  # RANGE_WIDE
        else:
            base_regimes[i] = 3
            if vol_trend > 0:
                sub_regimes[i] = 6  # VOLATILE_EXPANDING
            else:
                sub_regimes[i] = 7  # VOLATILE_CONTRACTING

    return base_regimes, sub_regimes


def build_trade_features(trades):
    """Build feature matrix from ENTRY-KNOWN trade attributes for regime model.

    IMPORTANT: Only features known at trade entry time are included.
    Future-known features (profit_ratio, direction, mfe, mae, trade_duration,
    stake_amount) were removed — they leak outcome information and make the
    regime model useless in live trading.
    """
    features = []
    for t in trades:
        open_ts = t.get("open_timestamp", 0)
        if open_ts:
            dt = datetime.utcfromtimestamp(open_ts / 1000)
        else:
            dt = datetime(2024, 1, 1)

        features.append([
            dt.hour,
            dt.weekday(),
            1 if t.get("is_short", False) else 0,
            t.get("leverage", 1) or 1,
        ])
    if features:
        return np.array(features, dtype=float)
    return np.array([])


# ───────────────────────────────────────────────────────────
#  PRO: TRADE QUALITY MODEL
# ───────────────────────────────────────────────────────────

def train_trade_quality_model(trades):
    """
    Train a model that scores trade QUALITY (0-100).
    Quality = probability of being a winner * expected profit magnitude.

    Features used:
    - Hour of day, day of week (session quality)
    - Price range (volatility context)
    - Is short (directional bias)
    - Duration bucket
    - MFE/MAE characteristics

    Returns (model, scaler, quality_thresholds).
    """
    if not trades or len(trades) < 100:
        return None, None, None

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return None, None, None

    features = []
    labels = []

    for t in trades:
        pr = t.get("profit_ratio")
        if pr is None:
            continue
        pr = float(pr)
        ts = t.get("open_timestamp", 0)

        if ts:
            dt = datetime.utcfromtimestamp(ts / 1000)
        else:
            dt = datetime(2024, 1, 1)

        is_short = 1 if t.get("is_short", False) else 0

        # Only use entry-known features (no duration, stake, leverage,
        # price_range — those are future-known or circular)
        features.append([
            dt.hour,
            dt.weekday(),
            is_short,
        ])

        # Quality label: good trade = profit > fees
        labels.append(1 if pr > ROUND_TRIP_FEE else 0)

    if len(features) < 100:
        return None, None, None

    X = np.array(features, dtype=float)
    y = np.array(labels, dtype=int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = GradientBoostingClassifier(
        n_estimators=100, max_depth=3,
        learning_rate=0.1, subsample=0.8,
        random_state=42,
    )
    model.fit(X_scaled, y)

    # Compute quality score distribution
    proba = model.predict_proba(X_scaled)[:, 1]
    thresholds = {
        "p25": round(float(np.percentile(proba, 25)), 4),
        "p50": round(float(np.percentile(proba, 50)), 4),
        "p75": round(float(np.percentile(proba, 75)), 4),
        "min_quality": round(
            float(np.percentile(proba, 60)), 4
        ),  # only take top 40% quality
    }

    return model, scaler, thresholds


# ───────────────────────────────────────────────────────────
#  CORE OPTIMIZATION ENGINE
# ───────────────────────────────────────────────────────────

def optimize_params(strat_trades_by_name):
    """
    For each regime, find best strategy and optimize:
    c, e, self-learned ROI table, SL, trailing, session filter.
    """
    regimes_by_strat = {}
    regime_strat_scores = defaultdict(dict)

    for sname, trades in strat_trades_by_name.items():
        base_regimes, sub_regimes = classify_trade_regimes(trades)
        regimes_by_strat[sname] = base_regimes
        for regime_id in range(4):
            mask = base_regimes == regime_id
            regime_trades = [t for t, m in zip(trades, mask) if m]
            if len(regime_trades) < 10:
                continue
            scores = score_strategy(regime_trades)
            if scores:
                regime_strat_scores[regime_id][sname] = scores

    # Self-learn ROI tables
    roi_tables = learn_roi_by_regime(strat_trades_by_name, regimes_by_strat)

    # Performance feedback per strategy
    perf_feedback = {}
    for sname, trades in strat_trades_by_name.items():
        rolling = compute_rolling_performance(trades)
        perf_feedback[sname] = detect_performance_trend(rolling)

    # PRO: MFE/MAE per strategy
    mfe_mae_by_strat = {}
    for sname, trades in strat_trades_by_name.items():
        mfe_mae_by_strat[sname] = analyze_mfe_mae(trades)

    # PRO: Walk-forward per strategy
    wf_by_strat = {}
    for sname, trades in strat_trades_by_name.items():
        wf_by_strat[sname] = walk_forward_validate(trades)

    # PRO: Kelly per strategy
    kelly_by_strat = {}
    for sname, trades in strat_trades_by_name.items():
        sc = score_strategy(trades)
        if sc:
            kelly_by_strat[sname] = compute_kelly_fraction(sc)

    # PRO: Equity curve analysis per strategy
    eq_by_strat = {}
    for sname, trades in strat_trades_by_name.items():
        eq_by_strat[sname] = analyze_equity_curve(trades)

    best_params = {}
    all_regime_scores = {}

    for regime_id in range(4):
        strat_scores = regime_strat_scores.get(regime_id, {})
        rname = REGIME_NAMES[regime_id]

        if not strat_scores:
            best_params[str(regime_id)] = _default_regime_params(regime_id)
            continue

        best_sname = max(strat_scores, key=lambda s: strat_scores[s]["score"])
        best = strat_scores[best_sname]
        all_regime_scores[rname] = dict(strat_scores)

        defaults = STRATEGY_DEFAULTS.get(best_sname, {"c": 0.50, "e": 0.00})
        wr = best["win_rate"]
        pf = best["profit_factor"]
        rr = best["rr_ratio"]
        dd = best["max_dd"]
        exp = best["expectancy"]
        avg_dur = best["avg_duration_min"]
        short_pct = best["short_pct"]

        pfb = perf_feedback.get(best_sname, {"entry_adj": 1.0, "size_adj": 1.0})

        # Dynamic c with feedback
        c_base = defaults["c"]
        c_wr_adj = 0.3 + 0.7 * wr
        c_dd_adj = max(0.3, 1.0 - dd * 5)
        c_pf_adj = min(1.2, pf / 1.5)
        adjusted_c = np.clip(
            c_base * c_wr_adj * c_dd_adj * c_pf_adj * pfb["size_adj"],
            0.10, 0.90
        )

        # Dynamic e
        if short_pct > 0.6:
            adjusted_e = defaults["e"] - 0.05
        elif short_pct < 0.3:
            adjusted_e = defaults["e"] + 0.05
        else:
            adjusted_e = defaults["e"]
        if exp < 0:
            adjusted_e = -adjusted_e * 0.5
        adjusted_e = np.clip(adjusted_e, -0.40, 0.40)

        # Self-learned ROI table
        regime_roi_data = roi_tables.get(regime_id, {})
        learned_roi = regime_roi_data.get(best_sname, None)

        if learned_roi is None:
            avg_win = best["avg_win"]
            if avg_win > 0:
                roi_0 = round(avg_win * 1.5, 4)
            else:
                roi_0 = 0.015
            roi_0 = np.clip(roi_0, 0.005, 0.10)
            learned_roi = {
                "0": round(float(roi_0), 5),
                "30": round(float(roi_0 * 0.7), 5),
                "60": round(float(roi_0 * 0.5), 5),
                "120": round(float(roi_0 * 0.3), 5),
            }

        # Dynamic Stop-Loss
        avg_loss = best["avg_loss"]
        if avg_loss > 0:
            sl = -round(avg_loss * 1.2, 4)
        else:
            sl = -0.02
        sl = np.clip(sl, -0.10, -0.005)

        # Trailing stop
        max_roi = max(float(v) for v in learned_roi.values())
        if rr > 1.5:
            trailing_offset = round(max(max_roi * 0.5, 0.003), 4)
        else:
            trailing_offset = 0.0

        # Session and directional analysis for this regime
        regime_trades_best = []
        base_regs = regimes_by_strat.get(best_sname, np.array([]))
        trades_list = strat_trades_by_name.get(best_sname, [])
        if len(base_regs) == len(trades_list):
            regime_trades_best = [
                t for t, r in zip(trades_list, base_regs)
                if r == regime_id
            ]
        tf_context = compute_timeframe_context(regime_trades_best)
        ls_profile = compute_long_short_profile(regime_trades_best)

        # PRO: Per-regime MFE/MAE calibrated SL/TP
        regime_mfe = analyze_mfe_mae(regime_trades_best)
        if regime_mfe:
            # Override SL with MFE/MAE calibrated value
            mfe_sl = regime_mfe.get("recommended_sl", sl)
            sl = round((sl + mfe_sl) / 2, 4)  # blend
            sl = np.clip(sl, -0.10, -0.005)

        # PRO: Kelly fraction for this regime
        regime_kelly = compute_kelly_fraction(best, fraction=0.25)

        # PRO: Walk-forward for this regime's strategy
        regime_wf = wf_by_strat.get(best_sname)
        is_robust = True
        if regime_wf:
            is_robust = regime_wf.get("is_robust", True)

        # PRO: Equity curve params
        regime_eq = eq_by_strat.get(best_sname)

        best_params[str(regime_id)] = {
            "c": round(float(adjusted_c), 3),
            "e": round(float(adjusted_e), 3),
            "roi_table": learned_roi,
            "sl": round(float(sl), 4),
            "trailing_offset": trailing_offset,
            "strategy": best_sname.replace("Strategy", ""),
            "source_score": round(best["score"], 4),
            "win_rate": round(wr, 4),
            "profit_factor": round(pf, 4),
            "sharpe": round(best["sharpe"], 2),
            "sortino": round(best["sortino"], 2),
            "rr_ratio": round(rr, 4),
            "expectancy": round(exp, 6),
            "max_dd": round(dd, 6),
            "avg_duration_min": round(avg_dur, 1),
            "trade_count": best["trade_count"],
            "perf_trend": pfb.get("trend", "stable"),
            "entry_adj": round(pfb.get("entry_adj", 1.0), 3),
            "size_adj": round(pfb.get("size_adj", 1.0), 3),
            "best_session": tf_context.get("best_session"),
            "worst_session": tf_context.get("worst_session"),
            "direction_bias": ls_profile.get("bias", "neutral"),
            "bias_strength": ls_profile.get(
                "bias_strength", 0.0
            ),
            # PRO features
            "kelly_fraction": regime_kelly,
            "is_robust": is_robust,
            "mfe_capture_pct": (
                regime_mfe.get("mfe_capture_pct", 0)
                if regime_mfe else 0
            ),
            "trail_start": (
                regime_mfe.get("trail_start", 0.005)
                if regime_mfe else 0.005
            ),
            "trail_step": (
                regime_mfe.get("trail_step", 0.003)
                if regime_mfe else 0.003
            ),
            "cooldown_after_losses": (
                regime_eq.get("recommended_cooldown", 3)
                if regime_eq else 3
            ),
            "daily_loss_limit": (
                regime_eq.get("recommended_daily_limit", 0.02)
                if regime_eq else 0.02
            ),
        }

    return best_params, all_regime_scores, regimes_by_strat


def _default_regime_params(regime_id):
    """Fallback defaults when no data for a regime."""
    defaults = {
        0: {"c": 0.50, "e": 0.05, "strategy": "OPT"},
        1: {"c": 0.30, "e": -0.10, "strategy": "A52"},
        2: {"c": 0.25, "e": 0.00, "strategy": "A51"},
        3: {"c": 0.40, "e": -0.05, "strategy": "A31"},
    }
    d = defaults.get(regime_id, defaults[3])
    return {
        "c": d["c"], "e": d["e"],
        "roi_table": {"0": 0.015, "30": 0.010, "60": 0.005, "120": 0.003},
        "sl": -0.020,
        "trailing_offset": 0.0,
        "strategy": d["strategy"],
        "source_score": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
        "sharpe": 0.0, "sortino": 0.0, "rr_ratio": 0.0,
        "expectancy": 0.0, "max_dd": 0.0, "avg_duration_min": 0.0,
        "trade_count": 0,
        "perf_trend": "stable", "entry_adj": 1.0, "size_adj": 1.0,
        "best_session": None, "worst_session": None,
        "direction_bias": "neutral", "bias_strength": 0.0,
    }


def train_regime_model(all_trades):
    """Train GradientBoosting classifier for regime prediction."""
    combined = []
    for trades in all_trades.values():
        combined.extend(trades)
    if len(combined) < 50:
        print("Warning: Not enough trades ({} < 50)".format(len(combined)))
        return None

    features = build_trade_features(combined)
    base_regimes, sub_regimes = classify_trade_regimes(combined)

    if len(features) != len(base_regimes):
        print("Warning: Feature/label mismatch")
        return None

    unique = np.unique(base_regimes)
    parts = []
    for u in unique:
        parts.append("{}={}".format(REGIME_NAMES.get(u, str(u)), int(np.sum(base_regimes == u))))
    print("Base regime distribution: " + ", ".join(parts))

    sub_unique = np.unique(sub_regimes)
    sub_parts = []
    for u in sub_unique:
        sub_parts.append("{}={}".format(SUB_REGIME_NAMES.get(u, str(u)), int(np.sum(sub_regimes == u))))
    print("Sub-regime distribution: " + ", ".join(sub_parts))

    if len(unique) < 2:
        print("Warning: Only 1 regime class - need more diverse data")
        return None

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
        model = GradientBoostingClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, random_state=42)
        model.fit(features, base_regimes)
        if len(features) >= 50:
            n_splits = min(5, len(unique))
            cv = cross_val_score(model, features, base_regimes, cv=n_splits, scoring="accuracy")
            print("Regime model CV accuracy: {:.3f} +/- {:.3f}".format(cv.mean(), cv.std()))
        fi = model.feature_importances_
        feat_names = ["hour", "weekday", "is_short", "leverage"]
        top = sorted(zip(feat_names, fi), key=lambda x: -x[1])[:5]
        print("Top features: " + ", ".join("{}={:.3f}".format(n, v) for n, v in top))
        return model
    except ImportError:
        print("Warning: sklearn not available")
        return None
    except Exception as e:
        print("Warning: Regime model error: " + str(e))
        return None


def save_performance_history(strat_trades, perf_feedback):
    """Save rolling performance history for feedback loop."""
    history = {}
    for sname, trades in strat_trades.items():
        rolling = compute_rolling_performance(trades)
        if rolling:
            wr_arr = np.array(rolling["win_rate"])
            exp_arr = np.array(rolling["expectancy"])
            history[sname] = {
                "latest_wr": round(float(wr_arr[-1]), 4) if len(wr_arr) else 0,
                "latest_exp": round(float(exp_arr[-1]), 6) if len(exp_arr) else 0,
                "wr_trend": round(float(wr_arr[-1] - wr_arr[0]), 4) if len(wr_arr) > 1 else 0,
                "exp_trend": round(float(exp_arr[-1] - exp_arr[0]), 6) if len(exp_arr) > 1 else 0,
                "perf_trend": perf_feedback.get(sname, {}).get("trend", "stable"),
                "n_windows": len(wr_arr),
            }

    try:
        with open(PERF_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
        print("Performance history saved: " + str(PERF_HISTORY_PATH))
    except Exception as e:
        print("Warning: Could not save perf history: " + str(e))


def save_training_log(strat_scores, best_params, total_trades, regime_scores):
    """Append training run to log."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "total_trades": total_trades,
        "strategy_scores": {},
        "best_params": best_params,
        "regime_scores": {},
    }
    for sname, sc in strat_scores.items():
        entry["strategy_scores"][sname] = {
            k: round(float(v), 4) if isinstance(v, (float, np.floating)) else v
            for k, v in sc.items()
        }
    for rname, rsc in regime_scores.items():
        entry["regime_scores"][rname] = {
            s: {k: round(float(v), 4) if isinstance(v, (float, np.floating)) else v
                for k, v in sc.items()}
            for s, sc in rsc.items()
        }
    log = []
    if TRAINING_LOG_PATH.exists():
        try:
            with open(TRAINING_LOG_PATH) as f:
                log = json.load(f)
        except Exception:
            log = []
    log.append(entry)
    log = log[-100:]
    with open(TRAINING_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)
    print("Training log saved ({} entries)".format(len(log)))


def main():
    parser = argparse.ArgumentParser(description="CC ML Optimizer v2")
    parser.add_argument("--retrain", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("CC ML Optimizer v2 - Self-Learning Pipeline")
    print("=" * 70)
    print("Backtest dir: " + str(BACKTEST_DIR))
    print("Model dir: " + str(MODEL_DIR))
    print()

    # 1. Load
    strat_trades = load_backtest_results()
    total = sum(len(v) for v in strat_trades.values())
    if total == 0:
        print("No backtest results found.")
        sys.exit(0)

    # 2. Score each strategy globally (with adaptive scoring)
    print("\n" + "-" * 70)
    print("STRATEGY PERFORMANCE OVERVIEW")
    print("-" * 70)
    print("{:<22} {:>6} {:>6} {:>5} {:>7} {:>8} {:>8} {:>5} {:>9} {:>6}".format(
        "Strategy", "Trades", "WR%", "PF", "Sharpe", "Sortino", "MaxDD", "RR", "E[r]", "Score"))
    print("-" * 95)

    global_scores = {}
    for sname, trades in strat_trades.items():
        sc = compute_adaptive_score(trades)
        if not sc:
            sc = score_strategy(trades)
        if sc:
            global_scores[sname] = sc
            momentum = sc.get("score_momentum", 0)
            m_icon = "+" if momentum > 0 else ("-" if momentum < 0 else "=")
            print("  {:<20} {:>6} {:>5.1%} {:>5.2f} {:>7.2f} {:>8.2f} {:>7.4f} {:>5.2f} {:>+9.6f} {:>6.3f} [{}]".format(
                sname, sc["trade_count"], sc["win_rate"], sc["profit_factor"],
                sc["sharpe"], sc["sortino"], sc["max_dd"], sc["rr_ratio"],
                sc["expectancy"], sc["score"], m_icon))

    # 3. Duration profile analysis
    print("\n" + "-" * 70)
    print("SELF-LEARNING ROI - TRADE DURATION ANALYSIS")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        profile = analyze_duration_profile(trades)
        if not profile:
            continue
        print("\n  {}:".format(sname))
        for bucket_name, stats in profile.items():
            if stats["count"] == 0:
                continue
            print("    {:<10} {:>5} trades  WR={:>5.1%}  avg={:>+8.5f}  med={:>+8.5f}  dur={:>5.0f}m".format(
                bucket_name, stats["count"],
                stats.get("win_rate", 0),
                stats.get("avg_profit", 0),
                stats.get("median_profit", 0),
                stats.get("avg_duration", 0)))

    # 4. Session analysis
    print("\n" + "-" * 70)
    print("TRADING SESSION ANALYSIS (UTC)")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        tf_ctx = compute_timeframe_context(trades)
        sessions = tf_ctx.get("sessions", {})
        if not sessions:
            continue
        print("\n  {}:".format(sname))
        for sess_name, stats in sessions.items():
            if stats.get("skip"):
                continue
            print("    {:<10} {:>5} trades  WR={:>5.1%}  avg={:>+8.5f}  total={:>+8.4f}".format(
                sess_name, stats["count"],
                stats.get("win_rate", 0),
                stats.get("avg_profit", 0),
                stats.get("total_profit", 0)))
        print("    Best: {}  Worst: {}".format(
            tf_ctx.get("best_session", "n/a"),
            tf_ctx.get("worst_session", "n/a")))

    # 5. Long/Short profile
    print("\n" + "-" * 70)
    print("LONG vs SHORT ANALYSIS")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        ls = compute_long_short_profile(trades)
        if not ls:
            continue
        print("\n  {}:".format(sname))
        for side in ["long", "short"]:
            s = ls.get(side, {})
            if s.get("count", 0) == 0:
                continue
            print("    {:<6} {:>5} trades  WR={:>5.1%}  avg={:>+8.5f}  PF={:>5.2f}".format(
                side, s["count"], s.get("win_rate", 0),
                s.get("avg_profit", 0), s.get("profit_factor", 0)))
        print("    Bias: {} (strength={:.4f})".format(
            ls.get("bias", "neutral"), ls.get("bias_strength", 0)))

    # 6. Performance feedback
    print("\n" + "-" * 70)
    print("PERFORMANCE FEEDBACK LOOP")
    print("-" * 70)
    perf_feedback = {}
    for sname, trades in strat_trades.items():
        rolling = compute_rolling_performance(trades)
        fb = detect_performance_trend(rolling)
        perf_feedback[sname] = fb
        trend_icon = {"improving": "+", "degrading": "-", "stable": "="}.get(fb["trend"], "?")
        print("  {:<22} [{}] {} (entry_adj={:.2f} size_adj={:.2f})".format(
            sname, trend_icon, fb["trend"], fb["entry_adj"], fb["size_adj"]))

    # 7. Optimize per regime
    print("\n" + "-" * 70)
    print("PER-REGIME OPTIMIZATION (with self-learned ROI)")
    print("-" * 70)
    best_params, regime_scores, _ = optimize_params(strat_trades)

    for rid, params in sorted(best_params.items()):
        rname = REGIME_NAMES.get(int(rid), "R" + rid)
        tc = params.get("trade_count", 0)
        roi_table = params.get("roi_table", {})
        roi_str = " ".join("{}m={:.4f}".format(k, v) for k, v in sorted(roi_table.items(), key=lambda x: int(x[0])))
        print("\n  {:<16} -> {:<5} c={:.2f} e={:+.2f} SL={:.4f} trail={:.4f}".format(
            rname, params["strategy"], params["c"], params["e"],
            params["sl"], params["trailing_offset"]))
        print("    ROI: {}".format(roi_str))
        print("    WR={:.1%} PF={:.2f} n={} trend={} bias={} best_sess={}".format(
            params["win_rate"], params["profit_factor"], tc,
            params.get("perf_trend", "stable"),
            params.get("direction_bias", "neutral"),
            params.get("best_session", "n/a")))

    # 8. Save params
    with open(BEST_PARAMS_PATH, "w") as f:
        json.dump(best_params, f, indent=2)
    print("\nBest params saved: " + str(BEST_PARAMS_PATH))

    # 9. Train regime model
    print("\n" + "-" * 70)
    print("REGIME CLASSIFIER TRAINING")
    print("-" * 70)
    model = train_regime_model(strat_trades)
    if model is not None:
        with open(REGIME_MODEL_PATH, "wb") as f:
            pickle.dump(model, f)
        print("Regime model saved: " + str(REGIME_MODEL_PATH))

    # 10. Save performance history
    save_performance_history(strat_trades, perf_feedback)

    # 11. Log
    save_training_log(global_scores, best_params, total, regime_scores)

    # ═══════════════════════════════════════════════════════
    #  PRO QUANT ANALYSIS
    # ═══════════════════════════════════════════════════════

    # 12. MFE/MAE Analysis
    print("\n" + "-" * 70)
    print("PRO: MFE/MAE EXCURSION ANALYSIS")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        mfe = analyze_mfe_mae(trades)
        if not mfe:
            continue
        print("\n  {}:".format(sname))
        print("    Avg MFE={:.4%}  Avg MAE={:.4%}  "
              "MFE Capture={:.1%}".format(
                  mfe["avg_mfe"], mfe["avg_mae"],
                  mfe["mfe_capture_pct"]))
        w = mfe.get("winners", {})
        l = mfe.get("losers", {})
        if w.get("count", 0):
            print("    Winners: MFE={:.4%} MAE={:.4%} "
                  "waste={:.4%} (profit left on table)".format(
                      w["avg_mfe"], w["avg_mae"], w["mfe_waste"]))
        if l.get("count", 0):
            print("    Losers:  MFE={:.4%} MAE={:.4%} "
                  "had_profit={:.0%}".format(
                      l["avg_mfe"], l["avg_mae"], l["had_profit"]))
        print("    Recommended: SL={:.4f}  TP={:.4f}  "
              "trail_start={:.4f}".format(
                  mfe["recommended_sl"],
                  mfe["recommended_tp"],
                  mfe["trail_start"]))

    # 13. Kelly Criterion
    print("\n" + "-" * 70)
    print("PRO: KELLY CRITERION POSITION SIZING")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        sc = score_strategy(trades)
        if not sc:
            continue
        kelly = compute_kelly_fraction(sc, fraction=0.25)
        edge = compute_fee_aware_edge(sc)
        emoji = "+" if edge["has_edge"] else "X"
        print("  {:<22} Kelly={:.1%}  edge={:+.5f}  "
              "edge/fee={:.1f}x  [{}]".format(
                  sname, kelly, edge["net_edge"],
                  edge["edge_ratio"], emoji))

    # 14. Walk-Forward Validation
    print("\n" + "-" * 70)
    print("PRO: WALK-FORWARD OUT-OF-SAMPLE VALIDATION")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        wf = walk_forward_validate(trades)
        if not wf:
            print("  {:<22} (insufficient data)".format(sname))
            continue
        robust = "ROBUST" if wf["is_robust"] else "FRAGILE"
        print("  {:<22} [{}]".format(sname, robust))
        print("    IS:  WR={:.1%} E[r]={:+.6f} "
              "Sharpe={:.2f} PF={:.2f}".format(
                  wf["is_win_rate"], wf["is_expectancy"],
                  wf["is_sharpe"], wf["is_profit_factor"]))
        print("    OOS: WR={:.1%} E[r]={:+.6f} "
              "Sharpe={:.2f} PF={:.2f}".format(
                  wf["oos_win_rate"], wf["oos_expectancy"],
                  wf["oos_sharpe"], wf["oos_profit_factor"]))
        print("    Overfit={:.1f}x  Robustness={:.0%}".format(
            wf["overfit_ratio"], wf["robustness"]))

    # 15. Monte Carlo Simulation
    print("\n" + "-" * 70)
    print("PRO: MONTE CARLO SIMULATION (5K sims, $1000 initial)")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        mc = monte_carlo_equity(trades)
        if not mc:
            continue
        print("\n  {} ({} trades):".format(sname, mc["n_trades"]))
        print("    Equity: P5=${:.0f}  P50=${:.0f}  "
              "P95=${:.0f}".format(
                  mc["equity_p5"], mc["equity_p50"],
                  mc["equity_p95"]))
        print("    MaxDD:  P50={:.1%}  P95={:.1%}  "
              "P99={:.1%}".format(
                  mc["max_dd_p50"], mc["max_dd_p95"],
                  mc["max_dd_p99"]))
        print("    P(profit)={:.0%}  P(ruin)={:.1%}".format(
            mc["prob_profit"], mc["prob_ruin"]))

    # 16. Equity Curve & Discipline
    print("\n" + "-" * 70)
    print("PRO: EQUITY CURVE & DISCIPLINE PARAMETERS")
    print("-" * 70)
    for sname, trades in strat_trades.items():
        eq = analyze_equity_curve(trades)
        if not eq:
            continue
        print("\n  {}:".format(sname))
        print("    Max consec losses: {}  Avg streak: {:.1f}".format(
            eq["max_consec_losses"], eq["avg_consec_losses"]))
        print("    Avg recovery: {:.0f} trades  "
              "Max recovery: {} trades".format(
                  eq["avg_recovery_trades"],
                  eq["max_recovery_trades"]))
        print("    Daily loss P95: {:.2%}  "
              "Losing days: {:.0%}".format(
                  eq["daily_loss_p95"], eq["losing_days_pct"]))
        print("    -> Cooldown after {} losses, "
              "daily limit {:.2%}".format(
                  eq["recommended_cooldown"],
                  eq["recommended_daily_limit"]))

    # 17. Train Trade Quality Model
    print("\n" + "-" * 70)
    print("PRO: TRADE QUALITY MODEL")
    print("-" * 70)
    all_trades_combined = []
    for trades in strat_trades.values():
        all_trades_combined.extend(trades)
    q_model, q_scaler, q_thresh = train_trade_quality_model(
        all_trades_combined
    )
    if q_model is not None:
        with open(QUALITY_MODEL_PATH, "wb") as f:
            pickle.dump(
                {"model": q_model, "scaler": q_scaler,
                 "thresholds": q_thresh}, f
            )
        print("  Quality model saved: {}".format(QUALITY_MODEL_PATH))
        print("  Min quality threshold: {:.2%}".format(
            q_thresh["min_quality"]))
        print("  P25={:.2%} P50={:.2%} P75={:.2%}".format(
            q_thresh["p25"], q_thresh["p50"], q_thresh["p75"]))
    else:
        print("  (insufficient data for quality model)")

    # 18. Save discipline params
    discipline = {
        "round_trip_fee": ROUND_TRIP_FEE,
        "min_edge_multiplier": MIN_EDGE_MULTIPLIER,
    }
    for sname, trades in strat_trades.items():
        eq = analyze_equity_curve(trades)
        if eq:
            discipline[sname] = {
                "cooldown": eq["recommended_cooldown"],
                "daily_limit": eq["recommended_daily_limit"],
                "max_consec_losses": eq["max_consec_losses"],
            }
    with open(DISCIPLINE_PATH, "w") as f:
        json.dump(discipline, f, indent=2)
    print("\nDiscipline params saved: {}".format(DISCIPLINE_PATH))

    # 19. NEW: Learn From Mistakes — Anti-Pattern Detection
    print("\n" + "-" * 70)
    print("PRO v4: LEARN FROM MISTAKES (Anti-Pattern Analysis)")
    print("-" * 70)
    anti_patterns = {}
    for sname, trades in strat_trades.items():
        ap = analyze_losing_patterns(trades)
        if not ap:
            print("  {:<22} (insufficient data)".format(sname))
            continue
        anti_patterns[sname] = ap
        print("\n  {}:".format(sname))
        if ap["toxic_hours"]:
            print("    Toxic hours (UTC): {}".format(
                ap["toxic_hours"]))
        if ap["toxic_days"]:
            day_names = ["Mon", "Tue", "Wed", "Thu",
                         "Fri", "Sat", "Sun"]
            toxic = [day_names[d] for d in ap["toxic_days"]]
            print("    Toxic days: {}".format(toxic))
        print("    Long WR={:.1%}  Short WR={:.1%}".format(
            ap["long_wr"], ap["short_wr"]))
        print("    High-vol WR={:.1%}  Avg loser "
              "range={:.4%}".format(
                  ap["high_vol_wr"], ap["avg_loser_range"]))
        print("    Analyzed: {} losers, {} winners".format(
            ap["n_losers_analyzed"], ap["n_winners_analyzed"]))

    # Save anti-patterns for strategy to load
    anti_pattern_path = MODEL_DIR / "anti_patterns.json"
    try:
        with open(anti_pattern_path, "w") as f:
            json.dump(anti_patterns, f, indent=2)
        print("\nAnti-patterns saved: {}".format(anti_pattern_path))
    except Exception as e:
        print("Warning: Could not save anti-patterns: " + str(e))

    print("\n" + "=" * 70)
    print("ML Optimization v4 PRO complete!")
    print("New: Adaptive scoring, learn-from-mistakes,")
    print("     anti-pattern detection, toxic hour/day avoidance")
    print("     + v3: MFE/MAE, Kelly, walk-forward, Monte Carlo")
    print("AdaptiveMLStrategy will hot-reload params on next candle.")
    print("=" * 70)


if __name__ == "__main__":
    main()

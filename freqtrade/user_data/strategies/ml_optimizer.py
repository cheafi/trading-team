#!/usr/bin/env python3
"""
ML Optimizer - Cheafi Trading Team (v3 PRO)
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


def score_strategy(trades):
    """Compute comprehensive performance metrics. Uses profit_ratio field."""
    if not trades:
        return None
    profits = []
    durations = []
    short_count = 0
    for t in trades:
        pr = t.get("profit_ratio")
        if pr is None:
            continue
        profits.append(float(pr))
        durations.append(t.get("trade_duration", 0) or 0)
        if t.get("is_short"):
            short_count += 1
    if not profits:
        return None
    profits = np.array(profits)
    n = len(profits)
    winners = int(np.sum(profits > 0))
    losers = int(np.sum(profits < 0))
    win_rate = winners / n

    gross_profit = float(np.sum(profits[profits > 0]))
    gross_loss = float(np.abs(np.sum(profits[profits < 0])))
    profit_factor = (gross_profit / gross_loss if gross_loss > 0 else 10.0)
    profit_factor = min(profit_factor, 10.0)

    cum = np.cumsum(profits)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    if np.std(profits) > 0:
        sharpe = np.mean(profits) / np.std(profits) * np.sqrt(105120)
    else:
        sharpe = 0.0

    downside = profits[profits < 0]
    if len(downside) > 0 and np.std(downside) > 0:
        sortino = np.mean(profits) / np.std(downside) * np.sqrt(105120)
    else:
        sortino = sharpe

    avg_win = float(np.mean(profits[profits > 0])) if winners else 0
    avg_loss = float(np.abs(np.mean(profits[profits < 0]))) if losers else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    expectancy = float(np.mean(profits))

    score = (
        0.25 * min(win_rate, 1.0)
        + 0.20 * min(max(sharpe / 5, -1), 1.0)
        + 0.15 * min(profit_factor / 3, 1.0)
        + 0.15 * min(rr_ratio / 2, 1.0)
        + 0.15 * max(1.0 - max_dd / 0.5, 0)
        + 0.10 * min(max(expectancy * 1000, -1), 1.0)
    )

    return {
        "trade_count": n,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_dd": round(max_dd, 6),
        "rr_ratio": round(rr_ratio, 4),
        "expectancy": round(expectancy, 6),
        "total_profit": round(float(np.sum(profits)), 6),
        "avg_duration_min": round(float(np.mean(durations)), 1),
        "short_pct": round(short_count / n, 3),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "score": round(score, 4),
    }


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


def analyze_duration_profile(trades):
    """
    Detailed duration analysis: win rate, expectancy, profit by bucket.
    Returns per-bucket stats for reporting.
    """
    if not trades:
        return {}
    profile = {}
    for bucket_name, (lo, hi) in DURATION_BUCKETS.items():
        bucket = [(t.get("profit_ratio", 0) or 0, t.get("trade_duration", 0) or 0)
                   for t in trades if lo <= (t.get("trade_duration", 0) or 0) < hi]
        if not bucket:
            profile[bucket_name] = {"count": 0}
            continue
        profits = [p for p, d in bucket]
        n = len(profits)
        wins = sum(1 for p in profits if p > 0)
        profile[bucket_name] = {
            "count": n,
            "win_rate": round(wins / n, 4) if n else 0,
            "avg_profit": round(float(np.mean(profits)), 6),
            "median_profit": round(float(np.median(profits)), 6),
            "avg_duration": round(float(np.mean([d for _, d in bucket])), 1),
            "best_profit": round(float(max(profits)), 6),
            "worst_loss": round(float(min(profits)), 6),
        }
    return profile


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
        mask = np.abs(timestamps - ts) <= window_ms
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
    """Build extended feature matrix from trade attributes for regime model."""
    features = []
    for t in trades:
        open_ts = t.get("open_timestamp", 0)
        if open_ts:
            dt = datetime.utcfromtimestamp(open_ts / 1000)
        else:
            dt = datetime(2024, 1, 1)
        open_rate = t.get("open_rate", 1) or 1
        max_rate = t.get("max_rate", open_rate)
        min_rate = t.get("min_rate", open_rate)
        close_rate = t.get("close_rate", open_rate)
        price_range = (max_rate - min_rate) / open_rate

        direction = (close_rate - open_rate) / open_rate

        if t.get("is_short", False):
            mfe = (open_rate - min_rate) / open_rate
            mae = (max_rate - open_rate) / open_rate
        else:
            mfe = (max_rate - open_rate) / open_rate
            mae = (open_rate - min_rate) / open_rate

        features.append([
            t.get("trade_duration", 0) or 0,
            1 if t.get("is_short", False) else 0,
            t.get("profit_ratio", 0) or 0,
            t.get("stake_amount", 100) or 100,
            dt.hour,
            dt.weekday(),
            t.get("leverage", 1) or 1,
            price_range,
            direction,
            mfe,
            mae,
        ])
    if features:
        return np.array(features, dtype=float)
    return np.array([])


# ───────────────────────────────────────────────────────────
#  PRO: MFE/MAE ANALYSIS (Maximum Favorable/Adverse Excursion)
# ───────────────────────────────────────────────────────────

def analyze_mfe_mae(trades):
    """
    Professional MFE/MAE analysis:
    - MFE = max unrealized profit during trade (how much we leave on table)
    - MAE = max unrealized loss during trade (how deep before recovery)

    Uses max_rate / min_rate from Freqtrade trade records.
    Returns calibrated SL/TP recommendations.
    """
    if not trades or len(trades) < 20:
        return None

    mfe_list = []
    mae_list = []
    mfe_capture = []  # % of MFE actually captured at exit
    winners = {"mfe": [], "mae": [], "profit": []}
    losers = {"mfe": [], "mae": [], "profit": []}

    for t in trades:
        pr = t.get("profit_ratio")
        if pr is None:
            continue
        pr = float(pr)
        open_rate = t.get("open_rate", 1) or 1
        max_rate = t.get("max_rate", open_rate)
        min_rate = t.get("min_rate", open_rate)
        is_short = t.get("is_short", False)

        if is_short:
            mfe = (open_rate - min_rate) / open_rate
            mae = (max_rate - open_rate) / open_rate
        else:
            mfe = (max_rate - open_rate) / open_rate
            mae = (open_rate - min_rate) / open_rate

        mfe_list.append(mfe)
        mae_list.append(mae)

        # How much of the MFE did we actually capture?
        if mfe > 0:
            capture = max(0, pr / mfe)
            mfe_capture.append(min(capture, 2.0))

        if pr > 0:
            winners["mfe"].append(mfe)
            winners["mae"].append(mae)
            winners["profit"].append(pr)
        else:
            losers["mfe"].append(mfe)
            losers["mae"].append(mae)
            losers["profit"].append(pr)

    mfe_arr = np.array(mfe_list)
    mae_arr = np.array(mae_list)

    result = {
        "n_trades": len(mfe_list),
        "avg_mfe": round(float(np.mean(mfe_arr)), 6),
        "avg_mae": round(float(np.mean(mae_arr)), 6),
        "median_mfe": round(float(np.median(mfe_arr)), 6),
        "median_mae": round(float(np.median(mae_arr)), 6),
        "p90_mfe": round(float(np.percentile(mfe_arr, 90)), 6),
        "p90_mae": round(float(np.percentile(mae_arr, 90)), 6),
        "mfe_capture_pct": round(
            float(np.mean(mfe_capture)) if mfe_capture else 0, 4
        ),
    }

    # Winner analysis
    if winners["mfe"]:
        w_mfe = np.array(winners["mfe"])
        w_mae = np.array(winners["mae"])
        w_pr = np.array(winners["profit"])
        result["winners"] = {
            "count": len(w_mfe),
            "avg_mfe": round(float(np.mean(w_mfe)), 6),
            "avg_mae": round(float(np.mean(w_mae)), 6),
            "avg_profit": round(float(np.mean(w_pr)), 6),
            "mfe_waste": round(
                float(np.mean(w_mfe - w_pr)), 6
            ),  # profit left on table
        }
    else:
        result["winners"] = {"count": 0}

    # Loser analysis
    if losers["mfe"]:
        l_mfe = np.array(losers["mfe"])
        l_mae = np.array(losers["mae"])
        l_pr = np.array(losers["profit"])
        result["losers"] = {
            "count": len(l_mfe),
            "avg_mfe": round(float(np.mean(l_mfe)), 6),
            "avg_mae": round(float(np.mean(l_mae)), 6),
            "avg_loss": round(float(np.mean(l_pr)), 6),
            "had_profit": round(
                float(np.mean(l_mfe > ROUND_TRIP_FEE)), 4
            ),  # % of losers that were positive at some point
        }
    else:
        result["losers"] = {"count": 0}

    # Calibrated SL recommendation: P75 of winner MAE
    # (losers that went deeper than this had no chance)
    if winners["mae"]:
        optimal_sl = -round(
            float(np.percentile(winners["mae"], 75)) * 1.1, 4
        )
        optimal_sl = max(optimal_sl, -0.05)
        result["recommended_sl"] = optimal_sl
    else:
        result["recommended_sl"] = -0.02

    # Calibrated TP recommendation: P50 of winner MFE
    # (exit when you've captured the typical max)
    if winners["mfe"]:
        optimal_tp = round(
            float(np.percentile(winners["mfe"], 50)) * 0.8, 4
        )
        optimal_tp = max(optimal_tp, 0.003)
        result["recommended_tp"] = optimal_tp
    else:
        result["recommended_tp"] = 0.01

    # Trailing stop calibration: start trailing at P30 of MFE
    if winners["mfe"]:
        trail_start = round(
            float(np.percentile(winners["mfe"], 30)), 4
        )
        trail_step = round(trail_start * 0.5, 4)
        result["trail_start"] = max(trail_start, 0.002)
        result["trail_step"] = max(trail_step, 0.001)
    else:
        result["trail_start"] = 0.005
        result["trail_step"] = 0.003

    return result


# ───────────────────────────────────────────────────────────
#  PRO: KELLY CRITERION (Optimal Position Sizing)
# ───────────────────────────────────────────────────────────

def compute_kelly_fraction(scores, fraction=0.25):
    """
    Kelly Criterion: f* = (bp - q) / b
    where b = avg_win/avg_loss, p = win_rate, q = 1-p

    Uses fractional Kelly (default 25%) for safety.
    Full Kelly is mathematically optimal but has huge variance.
    Pro quants use 0.15-0.30 of full Kelly.

    Returns fractional Kelly as position size multiplier.
    """
    if not scores:
        return 0.05

    wr = scores.get("win_rate", 0.5)
    avg_win = scores.get("avg_win", 0)
    avg_loss = scores.get("avg_loss", 0)

    if avg_loss <= 0 or avg_win <= 0:
        return 0.05

    b = avg_win / avg_loss  # odds ratio
    p = wr
    q = 1.0 - p

    full_kelly = (b * p - q) / b

    # Negative Kelly = no edge, don't trade
    if full_kelly <= 0:
        return 0.0

    # Fractional Kelly for safety
    f_kelly = full_kelly * fraction

    # Cap at 50% of capital (even fractional Kelly can be aggressive)
    return round(min(max(f_kelly, 0.02), 0.50), 4)


# ───────────────────────────────────────────────────────────
#  PRO: WALK-FORWARD VALIDATION
# ───────────────────────────────────────────────────────────

def walk_forward_validate(trades, n_windows=4):
    """
    Walk-forward validation: split trades chronologically into
    train/test windows. Train on each window, test on next.

    This detects overfitting: if in-sample >> out-of-sample,
    the strategy is curve-fitted.

    Returns in-sample vs out-of-sample metrics.
    """
    if not trades or len(trades) < 100:
        return None

    sorted_trades = sorted(
        trades, key=lambda t: t.get("open_timestamp", 0)
    )
    n = len(sorted_trades)

    # Each window = 1/(n_windows+1) of data
    # Train on 1 window, test on next
    window_size = n // (n_windows + 1)
    if window_size < 20:
        return None

    in_sample_results = []
    out_sample_results = []

    for i in range(n_windows):
        train_start = i * window_size
        train_end = train_start + window_size
        test_start = train_end
        test_end = min(test_start + window_size, n)

        train = sorted_trades[train_start:train_end]
        test = sorted_trades[test_start:test_end]

        if len(train) < 20 or len(test) < 10:
            continue

        is_scores = score_strategy(train)
        oos_scores = score_strategy(test)

        if is_scores and oos_scores:
            in_sample_results.append(is_scores)
            out_sample_results.append(oos_scores)

    if not in_sample_results:
        return None

    # Aggregate IS vs OOS metrics
    is_wr = np.mean([s["win_rate"] for s in in_sample_results])
    oos_wr = np.mean([s["win_rate"] for s in out_sample_results])
    is_exp = np.mean([s["expectancy"] for s in in_sample_results])
    oos_exp = np.mean([s["expectancy"] for s in out_sample_results])
    is_sharpe = np.mean([s["sharpe"] for s in in_sample_results])
    oos_sharpe = np.mean([s["sharpe"] for s in out_sample_results])
    is_pf = np.mean([s["profit_factor"] for s in in_sample_results])
    oos_pf = np.mean([s["profit_factor"] for s in out_sample_results])

    # Overfitting ratio: IS/OOS. > 1.5 = likely overfitted
    overfit_ratio = (
        (is_sharpe / oos_sharpe) if oos_sharpe > 0 else 10.0
    )

    # Robustness = what % of OOS windows were profitable
    oos_profitable = sum(
        1 for s in out_sample_results if s["expectancy"] > 0
    )
    robustness = oos_profitable / len(out_sample_results)

    return {
        "n_windows": n_windows,
        "window_size": window_size,
        "is_win_rate": round(float(is_wr), 4),
        "oos_win_rate": round(float(oos_wr), 4),
        "is_expectancy": round(float(is_exp), 6),
        "oos_expectancy": round(float(oos_exp), 6),
        "is_sharpe": round(float(is_sharpe), 2),
        "oos_sharpe": round(float(oos_sharpe), 2),
        "is_profit_factor": round(float(is_pf), 4),
        "oos_profit_factor": round(float(oos_pf), 4),
        "overfit_ratio": round(float(overfit_ratio), 2),
        "robustness": round(float(robustness), 4),
        "is_robust": robustness >= 0.50 and overfit_ratio < 2.0,
    }


# ───────────────────────────────────────────────────────────
#  PRO: MONTE CARLO SIMULATION
# ───────────────────────────────────────────────────────────

def monte_carlo_equity(trades, n_sims=5000, initial_capital=1000):
    """
    Monte Carlo simulation: randomize trade order N times,
    compute distribution of outcomes.

    Returns confidence intervals for:
    - Final equity
    - Maximum drawdown
    - Sharpe ratio
    - Probability of ruin (losing >50% of capital)
    """
    if not trades or len(trades) < 30:
        return None

    profits = np.array([
        float(t.get("profit_ratio", 0) or 0) for t in trades
    ])

    final_equities = []
    max_drawdowns = []
    n_trades = len(profits)

    rng = np.random.RandomState(42)

    for _ in range(n_sims):
        # Shuffle trade order
        shuffled = rng.permutation(profits)

        # Compute equity curve
        equity = initial_capital
        peak = equity
        max_dd = 0
        for p in shuffled:
            equity *= (1 + p)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    fe = np.array(final_equities)
    md = np.array(max_drawdowns)

    # Probability of ruin (losing >50%)
    prob_ruin = float(np.mean(fe < initial_capital * 0.50))

    # Probability of profit
    prob_profit = float(np.mean(fe > initial_capital))

    return {
        "n_simulations": n_sims,
        "n_trades": n_trades,
        "equity_p5": round(float(np.percentile(fe, 5)), 2),
        "equity_p25": round(float(np.percentile(fe, 25)), 2),
        "equity_p50": round(float(np.percentile(fe, 50)), 2),
        "equity_p75": round(float(np.percentile(fe, 75)), 2),
        "equity_p95": round(float(np.percentile(fe, 95)), 2),
        "equity_mean": round(float(np.mean(fe)), 2),
        "max_dd_p50": round(float(np.percentile(md, 50)), 4),
        "max_dd_p95": round(float(np.percentile(md, 95)), 4),
        "max_dd_p99": round(float(np.percentile(md, 99)), 4),
        "prob_profit": round(prob_profit, 4),
        "prob_ruin": round(prob_ruin, 4),
    }


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
        open_rate = t.get("open_rate", 1) or 1
        max_rate = t.get("max_rate", open_rate)
        min_rate = t.get("min_rate", open_rate)
        dur = t.get("trade_duration", 0) or 0
        ts = t.get("open_timestamp", 0)

        if ts:
            dt = datetime.utcfromtimestamp(ts / 1000)
        else:
            dt = datetime(2024, 1, 1)

        price_range = (max_rate - min_rate) / open_rate
        is_short = 1 if t.get("is_short", False) else 0

        features.append([
            dt.hour,
            dt.weekday(),
            is_short,
            price_range,
            dur,
            t.get("stake_amount", 100) or 100,
            t.get("leverage", 1) or 1,
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
#  PRO: EQUITY CURVE ANALYSIS
# ───────────────────────────────────────────────────────────

def analyze_equity_curve(trades):
    """
    Analyze equity curve characteristics for circuit breaker params.
    Returns:
    - Consecutive loss streaks (max, avg)
    - Recovery time from drawdowns
    - Equity curve EMA parameters for live circuit breaker
    """
    if not trades or len(trades) < 30:
        return None

    sorted_trades = sorted(
        trades, key=lambda t: t.get("open_timestamp", 0)
    )
    profits = [float(t.get("profit_ratio", 0) or 0)
               for t in sorted_trades]

    # Consecutive loss analysis
    max_consec_loss = 0
    current_streak = 0
    loss_streaks = []

    for p in profits:
        if p < 0:
            current_streak += 1
        else:
            if current_streak > 0:
                loss_streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        loss_streaks.append(current_streak)

    max_consec_loss = max(loss_streaks) if loss_streaks else 0
    avg_consec_loss = (
        float(np.mean(loss_streaks)) if loss_streaks else 0
    )

    # Equity curve
    equity = np.cumsum(profits)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity

    # Recovery analysis: how many trades to recover from DD
    recovery_trades = []
    in_dd = False
    dd_start = 0
    for i in range(len(drawdown)):
        if drawdown[i] > 0 and not in_dd:
            in_dd = True
            dd_start = i
        elif drawdown[i] == 0 and in_dd:
            recovery_trades.append(i - dd_start)
            in_dd = False

    # Daily loss limit: P95 of single-day losses
    # Group by date
    daily_pnl = defaultdict(float)
    for t in sorted_trades:
        ts = t.get("open_timestamp", 0)
        if ts:
            day = datetime.utcfromtimestamp(ts / 1000).date()
            daily_pnl[str(day)] += float(
                t.get("profit_ratio", 0) or 0
            )

    daily_losses = [v for v in daily_pnl.values() if v < 0]
    daily_loss_p95 = (
        abs(float(np.percentile(daily_losses, 95)))
        if daily_losses else 0.02
    )

    # Recommended circuit breaker params
    cooldown_after = min(max_consec_loss, 5)  # pause after this many losses
    daily_limit = round(daily_loss_p95 * 1.2, 4)  # daily max loss

    return {
        "max_consec_losses": max_consec_loss,
        "avg_consec_losses": round(avg_consec_loss, 1),
        "loss_streak_count": len(loss_streaks),
        "avg_recovery_trades": round(
            float(np.mean(recovery_trades)), 1
        ) if recovery_trades else 0,
        "max_recovery_trades": (
            max(recovery_trades) if recovery_trades else 0
        ),
        "daily_loss_p95": round(daily_loss_p95, 4),
        "recommended_cooldown": cooldown_after,
        "recommended_daily_limit": round(daily_limit, 4),
        "total_trading_days": len(daily_pnl),
        "losing_days_pct": round(
            len(daily_losses) / max(len(daily_pnl), 1), 4
        ),
    }


# ───────────────────────────────────────────────────────────
#  PRO: FEE-AWARE EDGE CALCULATION
# ───────────────────────────────────────────────────────────

def compute_fee_aware_edge(scores):
    """
    Calculate real edge after accounting for fees.
    Only trade if expected profit > MIN_EDGE_MULTIPLIER * fees.
    """
    if not scores:
        return {"has_edge": False, "net_edge": 0, "min_trades": 0}

    exp = scores.get("expectancy", 0)
    wr = scores.get("win_rate", 0)
    n = scores.get("trade_count", 0)

    # Gross edge (before fees included in backtest)
    # Note: Freqtrade backtests already include fees
    net_edge = exp  # already fee-adjusted

    # Minimum edge threshold
    min_edge = ROUND_TRIP_FEE * (MIN_EDGE_MULTIPLIER - 1)

    # Statistical significance: need sqrt(n) * edge > 2 * std
    # Approximate with trade count
    is_significant = n >= 50

    has_edge = (
        net_edge > 0
        and wr > 0.45
        and is_significant
    )

    return {
        "has_edge": has_edge,
        "net_edge": round(net_edge, 6),
        "gross_edge_est": round(net_edge + ROUND_TRIP_FEE, 6),
        "min_edge_threshold": round(min_edge, 6),
        "edge_ratio": round(
            net_edge / ROUND_TRIP_FEE if net_edge > 0 else 0, 2
        ),
        "is_significant": is_significant,
        "trade_count": n,
    }


# ───────────────────────────────────────────────────────────
#  PERFORMANCE FEEDBACK LOOP
# ───────────────────────────────────────────────────────────

def compute_rolling_performance(trades, window_trades=200):
    """
    Compute rolling win rate, expectancy, and Sharpe over sliding window.
    """
    if len(trades) < window_trades:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))
    profits = np.array([t.get("profit_ratio", 0) or 0 for t in sorted_trades])

    rolling_wr = []
    rolling_exp = []
    rolling_sharpe = []

    for i in range(window_trades, len(profits)):
        window = profits[i - window_trades:i]
        wr = np.mean(window > 0)
        exp = np.mean(window)
        std = np.std(window)
        sh = (exp / std * np.sqrt(105120)) if std > 0 else 0
        rolling_wr.append(float(wr))
        rolling_exp.append(float(exp))
        rolling_sharpe.append(float(sh))

    return {
        "win_rate": rolling_wr,
        "expectancy": rolling_exp,
        "sharpe": rolling_sharpe,
    }


def detect_performance_trend(rolling_metrics):
    """
    Detect if strategy performance is improving or degrading.
    Returns adjustment multipliers for entry thresholds.
    """
    if not rolling_metrics:
        return {"entry_adj": 1.0, "size_adj": 1.0, "trend": "stable"}

    wr = np.array(rolling_metrics["win_rate"])
    exp = np.array(rolling_metrics["expectancy"])

    if len(wr) < 20:
        return {"entry_adj": 1.0, "size_adj": 1.0, "trend": "stable"}

    n = len(wr)
    recent = slice(int(n * 0.8), n)
    early = slice(0, int(n * 0.2))

    wr_change = np.mean(wr[recent]) - np.mean(wr[early])
    exp_change = np.mean(exp[recent]) - np.mean(exp[early])

    if wr_change > 0.03 and exp_change > 0:
        return {"entry_adj": 0.95, "size_adj": 1.1, "trend": "improving"}
    elif wr_change < -0.05 or exp_change < -0.001:
        return {"entry_adj": 1.15, "size_adj": 0.8, "trend": "degrading"}
    else:
        return {"entry_adj": 1.0, "size_adj": 1.0, "trend": "stable"}


# ───────────────────────────────────────────────────────────
#  PRO v4: LEARN FROM MISTAKES (Anti-Pattern Detection)
# ───────────────────────────────────────────────────────────

def analyze_losing_patterns(trades):
    """
    Analyze losing trades to find common anti-patterns.
    Learns WHEN NOT to trade — the most profitable lesson.

    Returns conditions that correlate with losses:
    - Bad hours, bad days, bad volatility levels
    - Loss streaks that follow specific patterns
    """
    if not trades or len(trades) < 50:
        return None

    sorted_trades = sorted(
        trades, key=lambda t: t.get("open_timestamp", 0))

    losers = []
    winners = []
    for t in sorted_trades:
        pr = t.get("profit_ratio")
        if pr is None:
            continue
        ts = t.get("open_timestamp", 0)
        if ts:
            dt = datetime.utcfromtimestamp(ts / 1000)
        else:
            continue

        open_rate = t.get("open_rate", 1) or 1
        max_rate = t.get("max_rate", open_rate)
        min_rate = t.get("min_rate", open_rate)
        price_range = (max_rate - min_rate) / open_rate
        dur = t.get("trade_duration", 0) or 0
        is_short = t.get("is_short", False)

        entry = {
            "hour": dt.hour,
            "weekday": dt.weekday(),
            "is_short": is_short,
            "price_range": price_range,
            "duration": dur,
            "profit": float(pr),
        }

        if float(pr) < -ROUND_TRIP_FEE:
            losers.append(entry)
        elif float(pr) > ROUND_TRIP_FEE:
            winners.append(entry)

    if len(losers) < 20 or len(winners) < 20:
        return None

    # === Hour Analysis: find toxic hours ===
    hour_stats = {}
    for h in range(24):
        h_losers = [e for e in losers if e["hour"] == h]
        h_winners = [e for e in winners if e["hour"] == h]
        total = len(h_losers) + len(h_winners)
        if total < 5:
            continue
        wr = len(h_winners) / total
        avg_loss = (float(np.mean([e["profit"] for e in h_losers]))
                    if h_losers else 0)
        hour_stats[h] = {
            "win_rate": round(wr, 3),
            "avg_loss": round(avg_loss, 6),
            "count": total,
        }

    # Toxic hours: WR < 40% with enough data
    toxic_hours = [h for h, s in hour_stats.items()
                   if s["win_rate"] < 0.40 and s["count"] >= 10]

    # === Day of Week Analysis ===
    day_stats = {}
    for d in range(7):
        d_losers = [e for e in losers if e["weekday"] == d]
        d_winners = [e for e in winners if e["weekday"] == d]
        total = len(d_losers) + len(d_winners)
        if total < 10:
            continue
        wr = len(d_winners) / total
        day_stats[d] = {"win_rate": round(wr, 3), "count": total}

    toxic_days = [d for d, s in day_stats.items()
                  if s["win_rate"] < 0.40 and s["count"] >= 15]

    # === Volatility Analysis: find toxic volatility ===
    all_ranges = ([e["price_range"] for e in losers]
                  + [e["price_range"] for e in winners])
    range_median = float(np.median(all_ranges))

    # High-vol losers vs high-vol winners
    hv_losers = [e for e in losers if e["price_range"] > range_median]
    hv_winners = [e for e in winners if e["price_range"] > range_median]
    if hv_losers and hv_winners:
        hv_wr = len(hv_winners) / (len(hv_losers) + len(hv_winners))
    else:
        hv_wr = 0.5

    # === Direction Analysis ===
    short_losers = [e for e in losers if e["is_short"]]
    short_winners = [e for e in winners if e["is_short"]]
    long_losers = [e for e in losers if not e["is_short"]]
    long_winners = [e for e in winners if not e["is_short"]]

    short_total = len(short_losers) + len(short_winners)
    long_total = len(long_losers) + len(long_winners)
    short_wr = (len(short_winners) / short_total
                if short_total > 0 else 0.5)
    long_wr = (len(long_winners) / long_total
               if long_total > 0 else 0.5)

    # === Common Loser Profile ===
    avg_loser_range = float(np.mean(
        [e["price_range"] for e in losers]))
    avg_loser_dur = float(np.mean(
        [e["duration"] for e in losers]))

    return {
        "toxic_hours": toxic_hours,
        "toxic_days": toxic_days,
        "hour_stats": hour_stats,
        "day_stats": day_stats,
        "high_vol_wr": round(hv_wr, 3),
        "range_median": round(range_median, 6),
        "short_wr": round(short_wr, 3),
        "long_wr": round(long_wr, 3),
        "avg_loser_range": round(avg_loser_range, 6),
        "avg_loser_duration": round(avg_loser_dur, 1),
        "n_losers_analyzed": len(losers),
        "n_winners_analyzed": len(winners),
    }


def compute_adaptive_score(trades, recent_n=100):
    """
    Adaptive scoring: weight recent performance more heavily.
    Strategies that are improving get boosted;
    strategies that are degrading get penalized.

    This prevents the system from clinging to historically
    good strategies that have stopped working.
    """
    if not trades or len(trades) < 50:
        return None

    sorted_trades = sorted(
        trades, key=lambda t: t.get("open_timestamp", 0))

    # Overall score
    overall = score_strategy(sorted_trades)
    if not overall:
        return None

    # Recent score (last N trades)
    recent = sorted_trades[-min(recent_n, len(sorted_trades)):]
    recent_score = score_strategy(recent)
    if not recent_score:
        return overall

    # Blend: 40% overall + 60% recent (recency bias)
    blended = {}
    for key in ["win_rate", "profit_factor", "sharpe",
                "expectancy", "score"]:
        o_val = overall.get(key, 0)
        r_val = recent_score.get(key, 0)
        blended[key] = round(o_val * 0.4 + r_val * 0.6, 4)

    # Momentum: is recent better or worse than overall?
    momentum = recent_score["score"] - overall["score"]

    result = dict(overall)  # start with full metrics
    result["adaptive_score"] = blended["score"]
    result["recent_score"] = round(recent_score["score"], 4)
    result["score_momentum"] = round(momentum, 4)
    # Replace score with adaptive version
    result["score"] = blended["score"]

    return result


def compute_timeframe_context(trades):
    """
    Infer multi-timeframe market context from trade statistics.
    Groups trades by session (Asia/EU/US) to find best conditions.
    """
    if not trades:
        return {}

    sessions = {
        "asia": (0, 8),
        "europe": (8, 14),
        "us": (14, 22),
        "overlap": (22, 24),
    }

    session_stats = {}
    for session_name, (h_start, h_end) in sessions.items():
        session_trades = []
        for t in trades:
            ts = t.get("open_timestamp", 0)
            if ts:
                hour = datetime.utcfromtimestamp(ts / 1000).hour
                if h_start <= hour < h_end:
                    session_trades.append(t)

        if len(session_trades) < 10:
            session_stats[session_name] = {"count": len(session_trades), "skip": True}
            continue

        profits = [t.get("profit_ratio", 0) or 0 for t in session_trades]
        wins = sum(1 for p in profits if p > 0)
        session_stats[session_name] = {
            "count": len(session_trades),
            "win_rate": round(wins / len(profits), 4),
            "avg_profit": round(float(np.mean(profits)), 6),
            "total_profit": round(float(np.sum(profits)), 6),
            "skip": False,
        }

    valid = {k: v for k, v in session_stats.items() if not v.get("skip")}
    if valid:
        best_session = max(valid, key=lambda k: valid[k].get("avg_profit", -999))
        worst_session = min(valid, key=lambda k: valid[k].get("avg_profit", 999))
    else:
        best_session = worst_session = None

    return {
        "sessions": session_stats,
        "best_session": best_session,
        "worst_session": worst_session,
    }


def compute_long_short_profile(trades):
    """Analyze long vs short performance to calibrate directional bias."""
    if not trades:
        return {}

    longs = [t for t in trades if not t.get("is_short", False)]
    shorts = [t for t in trades if t.get("is_short", False)]

    result = {}
    for label, group in [("long", longs), ("short", shorts)]:
        if not group:
            result[label] = {"count": 0}
            continue
        profits = [t.get("profit_ratio", 0) or 0 for t in group]
        wins = sum(1 for p in profits if p > 0)
        gross_loss = float(np.abs(np.sum([p for p in profits if p < 0])))
        result[label] = {
            "count": len(group),
            "win_rate": round(wins / len(profits), 4),
            "avg_profit": round(float(np.mean(profits)), 6),
            "profit_factor": round(
                float(np.sum([p for p in profits if p > 0])) /
                max(gross_loss, 0.0001),
                4
            ),
        }

    l_wr = result.get("long", {}).get("win_rate", 0.5)
    s_wr = result.get("short", {}).get("win_rate", 0.5)
    l_pf = result.get("long", {}).get("profit_factor", 1.0)
    s_pf = result.get("short", {}).get("profit_factor", 1.0)

    if l_wr > s_wr + 0.05 and l_pf > s_pf:
        result["bias"] = "long"
        result["bias_strength"] = round(l_wr - s_wr, 4)
    elif s_wr > l_wr + 0.05 and s_pf > l_pf:
        result["bias"] = "short"
        result["bias_strength"] = round(s_wr - l_wr, 4)
    else:
        result["bias"] = "neutral"
        result["bias_strength"] = 0.0

    return result


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
        feat_names = ["duration", "is_short", "profit", "stake", "hour",
                      "weekday", "leverage", "price_range", "direction", "mfe", "mae"]
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
    parser = argparse.ArgumentParser(description="Cheafi ML Optimizer v2")
    parser.add_argument("--retrain", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("Cheafi ML Optimizer v2 - Self-Learning Pipeline")
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

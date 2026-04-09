"""
ML Scorer — Strategy evaluation and performance metrics.

Extracted from ml_optimizer.py (Phase 2 architecture split).
Pure functions that score strategies, compute edges, and detect trends.
"""

from collections import defaultdict
from datetime import datetime

import numpy as np

# Re-use constants from ml_optimizer (or define standalone)
FEE_PER_SIDE = 0.0005
ROUND_TRIP_FEE = FEE_PER_SIDE * 2
MIN_EDGE_MULTIPLIER = 2.0

DURATION_BUCKETS = {
    "short": (0, 30),
    "mid": (30, 120),
    "long": (120, 480),
    "extended": (480, 9999),
}


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
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 10.0
    profit_factor = min(profit_factor, 10.0)

    cum = np.cumsum(profits)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    if np.std(profits) > 0:
        sharpe = np.mean(profits) / np.std(profits) * np.sqrt(n)
    else:
        sharpe = 0.0

    downside = profits[profits < 0]
    if len(downside) > 0 and np.std(downside) > 0:
        sortino = np.mean(profits) / np.std(downside) * np.sqrt(n)
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


def analyze_duration_profile(trades):
    """Detailed duration analysis: win rate, expectancy, profit by bucket."""
    if not trades:
        return {}
    profile = {}
    for bucket_name, (lo, hi) in DURATION_BUCKETS.items():
        bucket = [
            (t.get("profit_ratio", 0) or 0, t.get("trade_duration", 0) or 0)
            for t in trades
            if lo <= (t.get("trade_duration", 0) or 0) < hi
        ]
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


def compute_fee_aware_edge(scores):
    """Calculate real edge after accounting for fees."""
    if not scores:
        return {"has_edge": False, "net_edge": 0, "min_trades": 0}

    exp = scores.get("expectancy", 0)
    n = scores.get("trade_count", 0)
    net_edge = exp
    min_edge = ROUND_TRIP_FEE * (MIN_EDGE_MULTIPLIER - 1)
    is_significant = n >= 50
    has_edge = net_edge > 0 and is_significant

    return {
        "has_edge": has_edge,
        "net_edge": round(net_edge, 6),
        "gross_edge_est": round(net_edge + ROUND_TRIP_FEE, 6),
        "min_edge_threshold": round(min_edge, 6),
        "edge_ratio": round(net_edge / ROUND_TRIP_FEE if net_edge > 0 else 0, 2),
        "is_significant": is_significant,
        "trade_count": n,
    }


def compute_rolling_performance(trades, window_trades=200):
    """Compute rolling win rate, expectancy, and Sharpe over sliding window."""
    if len(trades) < window_trades:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))
    profits = np.array([t.get("profit_ratio", 0) or 0 for t in sorted_trades])

    rolling_wr = []
    rolling_exp = []
    rolling_sharpe = []

    for i in range(window_trades, len(profits)):
        window = profits[i - window_trades : i]
        wr = np.mean(window > 0)
        exp = np.mean(window)
        std = np.std(window)
        sh = (exp / std * np.sqrt(window_trades)) if std > 0 else 0
        rolling_wr.append(float(wr))
        rolling_exp.append(float(exp))
        rolling_sharpe.append(float(sh))

    return {
        "win_rate": rolling_wr,
        "expectancy": rolling_exp,
        "sharpe": rolling_sharpe,
    }


def detect_performance_trend(rolling_metrics):
    """Detect if strategy performance is improving or degrading."""
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


def compute_adaptive_score(trades, recent_n=100):
    """Adaptive scoring: weight recent performance more heavily."""
    if not trades or len(trades) < 50:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))

    overall = score_strategy(sorted_trades)
    if not overall:
        return None

    recent = sorted_trades[-min(recent_n, len(sorted_trades)) :]
    recent_score = score_strategy(recent)
    if not recent_score:
        return overall

    blended = {}
    for key in ["win_rate", "profit_factor", "sharpe", "expectancy", "score"]:
        o_val = overall.get(key, 0)
        r_val = recent_score.get(key, 0)
        blended[key] = round(o_val * 0.4 + r_val * 0.6, 4)

    momentum = recent_score["score"] - overall["score"]

    result = dict(overall)
    result["adaptive_score"] = blended["score"]
    result["recent_score"] = round(recent_score["score"], 4)
    result["score_momentum"] = round(momentum, 4)
    result["score"] = blended["score"]

    return result


def compute_timeframe_context(trades):
    """Group trades by session (Asia/EU/US) to find best conditions."""
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
            session_stats[session_name] = {
                "count": len(session_trades),
                "skip": True,
            }
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
                float(np.sum([p for p in profits if p > 0])) / max(gross_loss, 0.0001),
                4,
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

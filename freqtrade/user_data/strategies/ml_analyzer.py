"""
ML Analyzer — Advanced trade analytics (MFE/MAE, walk-forward,
Monte Carlo, equity curve, anti-patterns).

Extracted from ml_optimizer.py (Phase 2 architecture split).
Pure analysis functions — no model training or persistence.
"""

from collections import defaultdict
from datetime import datetime

import numpy as np
from ml_scorer import score_strategy

FEE_PER_SIDE = 0.0005
ROUND_TRIP_FEE = FEE_PER_SIDE * 2


def analyze_mfe_mae(trades):
    """
    Professional MFE/MAE analysis:
    - MFE = max unrealized profit during trade
    - MAE = max unrealized loss during trade
    Returns calibrated SL/TP recommendations.
    """
    if not trades or len(trades) < 20:
        return None

    mfe_list = []
    mae_list = []
    mfe_capture = []
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
        "mfe_capture_pct": round(float(np.mean(mfe_capture)) if mfe_capture else 0, 4),
    }

    if winners["mfe"]:
        w_mfe = np.array(winners["mfe"])
        w_mae = np.array(winners["mae"])
        w_pr = np.array(winners["profit"])
        result["winners"] = {
            "count": len(w_mfe),
            "avg_mfe": round(float(np.mean(w_mfe)), 6),
            "avg_mae": round(float(np.mean(w_mae)), 6),
            "avg_profit": round(float(np.mean(w_pr)), 6),
            "mfe_waste": round(float(np.mean(w_mfe - w_pr)), 6),
        }
    else:
        result["winners"] = {"count": 0}

    if losers["mfe"]:
        l_mfe = np.array(losers["mfe"])
        l_mae = np.array(losers["mae"])
        l_pr = np.array(losers["profit"])
        result["losers"] = {
            "count": len(l_mfe),
            "avg_mfe": round(float(np.mean(l_mfe)), 6),
            "avg_mae": round(float(np.mean(l_mae)), 6),
            "avg_loss": round(float(np.mean(l_pr)), 6),
            "had_profit": round(float(np.mean(l_mfe > ROUND_TRIP_FEE)), 4),
        }
    else:
        result["losers"] = {"count": 0}

    if winners["mae"]:
        optimal_sl = -round(float(np.percentile(winners["mae"], 75)) * 1.1, 4)
        optimal_sl = max(optimal_sl, -0.05)
        result["recommended_sl"] = optimal_sl
    else:
        result["recommended_sl"] = -0.02

    if winners["mfe"]:
        optimal_tp = round(float(np.percentile(winners["mfe"], 50)) * 0.8, 4)
        optimal_tp = max(optimal_tp, 0.003)
        result["recommended_tp"] = optimal_tp
    else:
        result["recommended_tp"] = 0.01

    if winners["mfe"]:
        trail_start = round(float(np.percentile(winners["mfe"], 30)), 4)
        trail_step = round(trail_start * 0.5, 4)
        result["trail_start"] = max(trail_start, 0.002)
        result["trail_step"] = max(trail_step, 0.001)
    else:
        result["trail_start"] = 0.005
        result["trail_step"] = 0.003

    return result


def compute_kelly_fraction(scores, fraction=0.25):
    """Kelly Criterion: fractional Kelly position size multiplier."""
    if not scores:
        return 0.05

    wr = scores.get("win_rate", 0.5)
    avg_win = scores.get("avg_win", 0)
    avg_loss = scores.get("avg_loss", 0)

    if avg_loss <= 0 or avg_win <= 0:
        return 0.05

    b = avg_win / avg_loss
    p = wr
    q = 1.0 - p

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0

    f_kelly = full_kelly * fraction
    return round(min(max(f_kelly, 0.02), 0.50), 4)


def walk_forward_validate(trades, n_windows=5):
    """
    Walk-forward validation with EXPANDING (anchored) windows.

    Uses proper time-series cross-validation:
      Fold 1: train [0..20%],  test [20%..40%]
      Fold 2: train [0..40%],  test [40%..60%]
      Fold 3: train [0..60%],  test [60%..80%]
      Fold 4: train [0..80%],  test [80%..100%]
      (for n_windows=4)

    The training set GROWS each fold (anchored start), mimicking
    real deployment where you retrain on all available history.

    Returns dict with:
      - Per-fold IS/OOS metrics
      - Degradation slope (negative = performance decaying over time)
      - Overfit ratio (IS Sharpe / OOS Sharpe)
      - Robustness score (fraction of OOS folds profitable)
    """
    if not trades or len(trades) < 100:
        return None

    sorted_trades = sorted(
        trades, key=lambda t: t.get("open_timestamp", 0)
    )
    n = len(sorted_trades)
    fold_size = n // (n_windows + 1)
    if fold_size < 15:
        return None

    in_sample_results = []
    out_sample_results = []
    fold_details = []

    for i in range(n_windows):
        # Expanding: train always starts from 0
        train_end = (i + 1) * fold_size
        test_start = train_end
        test_end = min(test_start + fold_size, n)

        train = sorted_trades[0:train_end]
        test = sorted_trades[test_start:test_end]

        if len(train) < 20 or len(test) < 10:
            continue

        is_scores = score_strategy(train)
        oos_scores = score_strategy(test)

        if is_scores and oos_scores:
            in_sample_results.append(is_scores)
            out_sample_results.append(oos_scores)
            fold_details.append({
                "fold": i + 1,
                "train_size": len(train),
                "test_size": len(test),
                "is_wr": round(float(is_scores["win_rate"]), 4),
                "oos_wr": round(float(oos_scores["win_rate"]), 4),
                "is_exp": round(float(is_scores["expectancy"]), 6),
                "oos_exp": round(float(oos_scores["expectancy"]), 6),
                "is_sharpe": round(float(is_scores["sharpe"]), 2),
                "oos_sharpe": round(float(oos_scores["sharpe"]), 2),
            })

    if not in_sample_results:
        return None

    is_wr = np.mean([s["win_rate"] for s in in_sample_results])
    oos_wr = np.mean([s["win_rate"] for s in out_sample_results])
    is_exp = np.mean([s["expectancy"] for s in in_sample_results])
    oos_exp = np.mean([s["expectancy"] for s in out_sample_results])
    is_sharpe = np.mean([s["sharpe"] for s in in_sample_results])
    oos_sharpe = np.mean([s["sharpe"] for s in out_sample_results])
    is_pf = np.mean([s["profit_factor"] for s in in_sample_results])
    oos_pf = np.mean([s["profit_factor"] for s in out_sample_results])

    overfit_ratio = (is_sharpe / oos_sharpe) if oos_sharpe > 0 else 10.0
    oos_profitable = sum(
        1 for s in out_sample_results if s["expectancy"] > 0
    )
    robustness = oos_profitable / len(out_sample_results)

    # Degradation slope: linear fit of OOS expectancy over folds
    # Negative slope = performance decaying over time (bad sign)
    oos_exps = [s["expectancy"] for s in out_sample_results]
    if len(oos_exps) >= 3:
        x = np.arange(len(oos_exps))
        coeffs = np.polyfit(x, oos_exps, 1)
        degradation_slope = float(coeffs[0])
    else:
        degradation_slope = 0.0

    return {
        "method": "expanding_window",
        "n_windows": n_windows,
        "fold_size": fold_size,
        "folds": fold_details,
        "is_win_rate": round(float(is_wr), 4),
        "oos_win_rate": round(float(oos_wr), 4),
        "is_expectancy": round(float(is_exp), 6),
        "oos_expectancy": round(float(oos_exp), 6),
        "is_sharpe": round(float(is_sharpe), 2),
        "oos_sharpe": round(float(oos_sharpe), 2),
        "is_profit_factor": round(float(is_pf), 4),
        "oos_profit_factor": round(float(oos_pf), 4),
        "overfit_ratio": round(float(overfit_ratio), 2),
        "degradation_slope": round(degradation_slope, 6),
        "robustness": round(float(robustness), 4),
        "is_robust": robustness >= 0.50 and overfit_ratio < 2.0
                     and degradation_slope > -0.005,
    }


def monte_carlo_equity(trades, n_sims=5000, initial_capital=1000):
    """Monte Carlo simulation: confidence intervals & probability of ruin."""
    if not trades or len(trades) < 30:
        return None

    profits = np.array([float(t.get("profit_ratio", 0) or 0) for t in trades])

    final_equities = []
    max_drawdowns = []
    n_trades = len(profits)
    rng = np.random.RandomState(42)

    for _ in range(n_sims):
        shuffled = rng.permutation(profits)
        equity = initial_capital
        peak = equity
        max_dd = 0
        for p in shuffled:
            equity *= 1 + p
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    fe = np.array(final_equities)
    md = np.array(max_drawdowns)

    prob_ruin = float(np.mean(fe < initial_capital * 0.50))
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


def analyze_equity_curve(trades):
    """Analyze equity curve for circuit breaker params."""
    if not trades or len(trades) < 30:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))
    profits = [float(t.get("profit_ratio", 0) or 0) for t in sorted_trades]

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
    avg_consec_loss = float(np.mean(loss_streaks)) if loss_streaks else 0

    equity = np.cumsum(profits)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity

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

    daily_pnl = defaultdict(float)
    for t in sorted_trades:
        ts = t.get("open_timestamp", 0)
        if ts:
            day = datetime.utcfromtimestamp(ts / 1000).date()
            daily_pnl[str(day)] += float(t.get("profit_ratio", 0) or 0)

    daily_losses = [v for v in daily_pnl.values() if v < 0]
    daily_loss_p95 = (
        abs(float(np.percentile(daily_losses, 95))) if daily_losses else 0.02
    )

    cooldown_after = min(max_consec_loss, 5)
    daily_limit = round(daily_loss_p95 * 1.2, 4)

    return {
        "max_consec_losses": max_consec_loss,
        "avg_consec_losses": round(avg_consec_loss, 1),
        "loss_streak_count": len(loss_streaks),
        "avg_recovery_trades": (
            round(float(np.mean(recovery_trades)), 1) if recovery_trades else 0
        ),
        "max_recovery_trades": (max(recovery_trades) if recovery_trades else 0),
        "daily_loss_p95": round(daily_loss_p95, 4),
        "recommended_cooldown": cooldown_after,
        "recommended_daily_limit": round(daily_limit, 4),
        "total_trading_days": len(daily_pnl),
        "losing_days_pct": round(len(daily_losses) / max(len(daily_pnl), 1), 4),
    }


def analyze_losing_patterns(trades):
    """Analyze losing trades to find anti-patterns (when NOT to trade)."""
    if not trades or len(trades) < 50:
        return None

    sorted_trades = sorted(trades, key=lambda t: t.get("open_timestamp", 0))

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

    # Hour analysis
    hour_stats = {}
    for h in range(24):
        h_losers = [e for e in losers if e["hour"] == h]
        h_winners = [e for e in winners if e["hour"] == h]
        total = len(h_losers) + len(h_winners)
        if total < 5:
            continue
        wr = len(h_winners) / total
        avg_loss = float(np.mean([e["profit"] for e in h_losers])) if h_losers else 0
        hour_stats[h] = {
            "win_rate": round(wr, 3),
            "avg_loss": round(avg_loss, 6),
            "count": total,
        }

    toxic_hours = [
        h for h, s in hour_stats.items() if s["win_rate"] < 0.40 and s["count"] >= 10
    ]

    # Day of week analysis
    day_stats = {}
    for d in range(7):
        d_losers = [e for e in losers if e["weekday"] == d]
        d_winners = [e for e in winners if e["weekday"] == d]
        total = len(d_losers) + len(d_winners)
        if total < 10:
            continue
        wr = len(d_winners) / total
        day_stats[d] = {"win_rate": round(wr, 3), "count": total}

    toxic_days = [
        d for d, s in day_stats.items() if s["win_rate"] < 0.40 and s["count"] >= 15
    ]

    # Volatility analysis
    all_ranges = [e["price_range"] for e in losers] + [
        e["price_range"] for e in winners
    ]
    range_median = float(np.median(all_ranges))

    hv_losers = [e for e in losers if e["price_range"] > range_median]
    hv_winners = [e for e in winners if e["price_range"] > range_median]
    if hv_losers and hv_winners:
        hv_wr = len(hv_winners) / (len(hv_losers) + len(hv_winners))
    else:
        hv_wr = 0.5

    # Direction analysis
    short_losers = [e for e in losers if e["is_short"]]
    short_winners = [e for e in winners if e["is_short"]]
    long_losers = [e for e in losers if not e["is_short"]]
    long_winners = [e for e in winners if not e["is_short"]]

    short_total = len(short_losers) + len(short_winners)
    long_total = len(long_losers) + len(long_winners)
    short_wr = len(short_winners) / short_total if short_total > 0 else 0.5
    long_wr = len(long_winners) / long_total if long_total > 0 else 0.5

    avg_loser_range = float(np.mean([e["price_range"] for e in losers]))
    avg_loser_dur = float(np.mean([e["duration"] for e in losers]))

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

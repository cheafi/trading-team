"""
Discipline Engine — Risk gates, journaling, and state persistence
=================================================================
Extracts discipline system from AdaptiveMLStrategy for
maintainability. Handles:

  - Kill switch check
  - Consecutive loss cooldown
  - Daily loss limit
  - Equity curve circuit breaker
  - Max drawdown halt (auto-kills at 20%)
  - Per-pair position limit
  - Cross-pair correlation filter
  - Decision journal (JSONL append-only)
  - Trade replay logging
  - Discipline state persistence
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def load_discipline_state(path: Path, state: dict) -> dict:
    """
    Restore volatile discipline counters from disk.
    Only restores if same day (daily counters reset at midnight).

    Args:
        path: Path to discipline_state.json
        state: Current state dict to update in-place

    Returns:
        Updated state dict
    """
    if not path.exists():
        return state
    try:
        with open(path, "r") as f:
            saved = json.load(f)
        saved_date = saved.get("date")
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if saved_date == today:
            state["consecutive_losses"] = saved.get(
                "consecutive_losses", state.get("consecutive_losses", 0)
            )
            state["daily_pnl"] = saved.get(
                "daily_pnl", state.get("daily_pnl", 0.0)
            )
            state["daily_trades"] = saved.get(
                "daily_trades", state.get("daily_trades", 0)
            )
            state["recent_results"] = saved.get(
                "recent_results", state.get("recent_results", [])
            )
            logger.info(
                "Discipline state restored: losses=%d pnl=%.4f trades=%d",
                state["consecutive_losses"],
                state["daily_pnl"],
                state["daily_trades"],
            )
        else:
            logger.info(
                "Discipline state from %s — new day %s, resetting",
                saved_date, today,
            )
    except Exception as e:
        logger.warning("Failed to load discipline state: %s", e)
    return state


def save_discipline_state(path: Path, state: dict, max_recent: int = 20):
    """
    Persist volatile discipline counters to disk.
    Called after every trade exit and daily counter reset.
    """
    try:
        recent = state.get("recent_results", [])[-max_recent:]
        data = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "consecutive_losses": state.get("consecutive_losses", 0),
            "daily_pnl": round(state.get("daily_pnl", 0.0), 6),
            "daily_trades": state.get("daily_trades", 0),
            "recent_results": [round(r, 6) for r in recent],
            "saved_at": datetime.utcnow().isoformat(),
        }
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=1)
        tmp_path.replace(path)  # atomic on POSIX
    except Exception as e:
        logger.warning("Failed to save discipline state: %s", e)


def check_max_drawdown(
    equity_curve: list,
    kill_switch_path: Path,
    current_time,
    max_dd_halt: float = 0.20,
    max_dd_warn: float = 0.15,
) -> str:
    """
    Strategy-level max drawdown halt.
    If equity curve shows > max_dd_halt, auto-enable kill switch.
    Returns: 'halt', 'warn', or 'ok'.
    """
    if len(equity_curve) < 5:
        return "ok"
    peak = max(equity_curve)
    current = equity_curve[-1]
    if peak <= 0:
        return "ok"
    dd = (peak - current) / abs(peak) if peak != 0 else 0
    if dd >= max_dd_halt:
        try:
            kill_switch_path.touch()
            logger.critical(
                "MAX DD HALT: %.1f%% drawdown — kill switch "
                "auto-enabled at %s", dd * 100, current_time,
            )
        except Exception:
            pass
        return "halt"
    if dd >= max_dd_warn:
        logger.warning(
            "DD WARNING: %.1f%% drawdown at %s",
            dd * 100, current_time,
        )
        return "warn"
    return "ok"


def check_pair_exposure(
    pair: str,
    dp,
    max_positions: int = 2,
) -> bool:
    """
    Per-pair position limit.
    Returns True if pair is within limit, False if blocked.
    """
    try:
        open_trades = dp.get_trades() if hasattr(dp, 'get_trades') else []
        if not open_trades:
            from freqtrade.persistence import Trade
            open_trades = Trade.get_trades_proxy(is_open=True)
        count = sum(
            1 for t in open_trades
            if getattr(t, 'pair', '') == pair
        )
        return count < max_positions
    except Exception:
        return True  # fail open


def check_correlation_exposure(
    pair: str,
    side: str,
    correlation_groups: dict,
    max_same_direction: int = 2,
) -> bool:
    """
    Cross-pair correlation filter.
    Block entry if too many correlated pairs already open
    in the same direction.
    """
    try:
        from freqtrade.persistence import Trade
        open_trades = Trade.get_trades_proxy(is_open=True)
        if not open_trades:
            return True

        pair_group = None
        for group_name, members in correlation_groups.items():
            if pair in members:
                pair_group = group_name
                break
        if pair_group is None:
            return True

        group_members = correlation_groups[pair_group]
        same_dir_count = sum(
            1 for t in open_trades
            if getattr(t, 'pair', '') in group_members
            and getattr(t, 'is_short', False) == (side == 'short')
        )
        return same_dir_count < max_same_direction
    except Exception:
        return True  # fail open


def snap_features(row) -> dict:
    """Extract feature snapshot from a dataframe row for journaling."""
    snap_keys = [
        "adx", "atr_norm", "ema_slope", "bb_width",
        "vol_ratio", "rsi", "macd_hist", "direction_score",
        "regime", "sub_regime", "trend_1h", "rsi_15m",
        "volume", "volume_sma",
    ]
    snap = {}
    for k in snap_keys:
        v = row.get(k)
        if v is not None and not (
            isinstance(v, float) and np.isnan(v)
        ):
            snap[k] = (
                round(float(v), 4)
                if isinstance(v, (float, np.floating))
                else int(v)
            )
    return snap


def log_decision(
    pair: str,
    side: str,
    decision: str,
    reason: str,
    current_time,
    journal_path: Path,
    rejection_log_path: Path,
    rejection_log: list,
    max_rejections: int = 100,
    rate=None,
    features=None,
    edge_score=None,
    quality_threshold=None,
    risk_state: dict = None,
    model_ts: float = 0,
) -> list:
    """
    Decision Journal v4 — append-only JSONL.
    Every decision (accept AND reject) is persisted.
    Returns updated rejection_log list.
    """
    entry = {
        "time": str(current_time),
        "pair": pair,
        "side": side,
        "decision": decision,
        "reason": reason,
        "rate": round(float(rate), 8) if rate is not None else None,
        "edge_score": round(float(edge_score), 4) if edge_score is not None else None,
        "quality_threshold": round(float(quality_threshold), 4) if quality_threshold is not None else None,
        "risk": risk_state or {},
        "model_ts": model_ts,
    }
    if features is not None:
        snap = snap_features(features)
        entry["features"] = snap
        entry["regime"] = snap.get("regime")
        entry["direction_score"] = snap.get("direction_score")

    # Append-only JSONL (durable — never truncated)
    try:
        with open(journal_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    # Backward-compat: keep last N rejections in old format
    if decision == "reject":
        rejection_log.append(entry)
        if len(rejection_log) > max_rejections:
            rejection_log = rejection_log[-max_rejections:]
        try:
            with open(rejection_log_path, "w") as f:
                json.dump(rejection_log[-50:], f, indent=1)
        except Exception:
            pass

    return rejection_log


def log_trade_entry(
    pair: str,
    side: str,
    entry_tag: str,
    regime: int,
    rate: float,
    current_time,
    features_row,
    params: dict,
    risk_state: dict,
    model_ts: float,
    replay_log: list,
    replay_path: Path,
    max_replay: int = 200,
    shadow=None,
) -> list:
    """
    Trade Replay — log accepted entry with full context.
    Returns updated replay_log list.
    """
    entry = {
        "event": "entry",
        "time": str(current_time),
        "pair": pair,
        "side": side,
        "entry_tag": entry_tag,
        "rate": round(float(rate), 8),
        "regime": regime,
        "features": snap_features(features_row),
        "risk": risk_state,
        "params": {
            "c": params.get("c"),
            "e": params.get("e"),
            "sl": params.get("sl"),
            "kelly_fraction": params.get("kelly_fraction"),
        },
        "model_ts": model_ts,
    }
    if shadow is not None:
        entry["shadow"] = shadow
    replay_log.append(entry)
    _persist_replay(replay_log, replay_path, max_replay)
    return replay_log


def log_trade_exit(
    pair: str,
    trade,
    exit_reason: str,
    profit: float,
    rate: float,
    current_time,
    dp,
    timeframe: str,
    replay_log: list,
    replay_path: Path,
    max_replay: int = 200,
    risk_state: dict = None,
) -> list:
    """
    Trade Replay — log exit with PnL attribution.
    Returns updated replay_log list.
    """
    try:
        duration = (
            current_time - trade.open_date_utc
        ).total_seconds() / 60
    except Exception:
        duration = 0

    features = {}
    try:
        df, _ = dp.get_analyzed_dataframe(pair, timeframe)
        if df is not None and len(df) > 0:
            features = snap_features(df.iloc[-1])
    except Exception:
        pass

    entry = {
        "event": "exit",
        "time": str(current_time),
        "pair": pair,
        "side": "short" if trade.is_short else "long",
        "exit_reason": exit_reason,
        "profit_ratio": round(float(profit), 6),
        "entry_rate": round(float(trade.open_rate), 8),
        "exit_rate": round(float(rate), 8),
        "duration_min": round(duration, 1),
        "entry_tag": trade.enter_tag,
        "features_at_exit": features,
        "risk": risk_state or {},
    }
    replay_log.append(entry)
    _persist_replay(replay_log, replay_path, max_replay)
    return replay_log


def _persist_replay(replay_log: list, path: Path, max_entries: int = 200):
    """Persist trade replay log to disk (last N entries)."""
    if len(replay_log) > max_entries:
        replay_log[:] = replay_log[-max_entries:]
    try:
        with open(path, "w") as f:
            json.dump(replay_log[-100:], f, indent=1)
    except Exception:
        pass

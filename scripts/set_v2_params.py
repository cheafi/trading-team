#!/usr/bin/env python3
"""Set v2-compatible best_params with v3 pro fields."""
import json

bp = {
    "0": {
        "c": 0.62, "e": -0.05, "strategy": "A31",
        "roi_table": {"0": 0.0152, "30": 0.010, "60": 0.006, "120": 0.003},
        "sl": -0.0066, "trailing_offset": 0.0076,
        "entry_adj": 1.0, "size_adj": 1.0,
        "best_session": None, "worst_session": None,
        "direction_bias": "neutral", "bias_strength": 0.0,
        "win_rate": 0.37, "profit_factor": 0.90, "expectancy": -0.001,
        "kelly_fraction": 0.0, "is_robust": True,
        "trail_start": 0.006, "trail_step": 0.003,
        "cooldown_after_losses": 5, "daily_loss_limit": 0.02,
        "trade_count": 184, "max_dd": 0.01,
    },
    "1": {
        "c": 0.10, "e": -0.03, "strategy": "A51",
        "roi_table": {"0": 0.005, "30": 0.004, "60": 0.003, "120": 0.002},
        "sl": -0.005, "trailing_offset": 0.0,
        "entry_adj": 1.0, "size_adj": 1.0,
        "best_session": None, "worst_session": None,
        "direction_bias": "neutral", "bias_strength": 0.0,
        "win_rate": 0.38, "profit_factor": 0.67, "expectancy": -0.0008,
        "kelly_fraction": 0.0, "is_robust": True,
        "trail_start": 0.005, "trail_step": 0.003,
        "cooldown_after_losses": 5, "daily_loss_limit": 0.02,
        "trade_count": 3000, "max_dd": 0.03,
    },
    "2": {
        "c": 0.11, "e": 0.00, "strategy": "A31",
        "roi_table": {"0": 0.005, "30": 0.004, "60": 0.003, "120": 0.002},
        "sl": -0.005, "trailing_offset": 0.0,
        "entry_adj": 1.0, "size_adj": 1.0,
        "best_session": None, "worst_session": None,
        "direction_bias": "neutral", "bias_strength": 0.0,
        "win_rate": 0.41, "profit_factor": 0.79, "expectancy": -0.001,
        "kelly_fraction": 0.0, "is_robust": True,
        "trail_start": 0.005, "trail_step": 0.003,
        "cooldown_after_losses": 5, "daily_loss_limit": 0.02,
        "trade_count": 134, "max_dd": 0.01,
    },
    "3": {
        "c": 0.27, "e": -0.10, "strategy": "A52",
        "roi_table": {"0": 0.016, "30": 0.010, "60": 0.006, "120": 0.003},
        "sl": -0.0059, "trailing_offset": 0.008,
        "entry_adj": 1.0, "size_adj": 1.0,
        "best_session": None, "worst_session": None,
        "direction_bias": "neutral", "bias_strength": 0.0,
        "win_rate": 0.45, "profit_factor": 0.77, "expectancy": -0.0009,
        "kelly_fraction": 0.0, "is_robust": True,
        "trail_start": 0.006, "trail_step": 0.003,
        "cooldown_after_losses": 5, "daily_loss_limit": 0.02,
        "trade_count": 4973, "max_dd": 0.07,
    },
}

path = "/freqtrade/user_data/ml_models/best_params.json"
with open(path, "w") as f:
    json.dump(bp, f, indent=2)
print("v2-compatible best_params saved with is_robust=True")
for rid in ["0", "1", "2", "3"]:
    p = bp[rid]
    print(f"  R{rid}: {p['strategy']} e={p['e']} kelly={p['kelly_fraction']}")

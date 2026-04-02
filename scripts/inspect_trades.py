#!/usr/bin/env python3
"""Inspect backtest trade schema"""
import json, zipfile, glob, numpy as np

import os
BASE = os.path.join(os.path.dirname(__file__), '..', 'freqtrade', 'user_data', 'backtest_results')
zips = sorted(glob.glob(os.path.join(BASE, 'backtest-result-*.zip')))
print(f"Found {len(zips)} zip files\n")

all_trades = {}
for z in zips:
    with zipfile.ZipFile(z) as zz:
        j = [n for n in zz.namelist() if n.endswith('.json') and not n.endswith('_config.json')][0]
        data = json.load(zz.open(j))
    for sname, sdata in data.get('strategy', {}).items():
        trades = sdata.get('trades', [])
        if sname not in all_trades:
            all_trades[sname] = []
        all_trades[sname].extend(trades)

for sname, trades in all_trades.items():
    if not trades:
        continue
    t0 = trades[0]
    profits = [t.get('profit_ratio', 0) for t in trades]
    winners = sum(1 for p in profits if p > 0)
    losers = sum(1 for p in profits if p < 0)
    print(f"=== {sname} ({len(trades)} trades) ===")
    print(f"  Keys: {sorted(t0.keys())}")
    print(f"  profit_ratio: {t0.get('profit_ratio')}")
    print(f"  profit_abs: {t0.get('profit_abs')}")
    print(f"  profit_percent: {t0.get('profit_percent', 'MISSING')}")
    print(f"  close_profit: {t0.get('close_profit', 'MISSING')}")
    print(f"  trade_duration: {t0.get('trade_duration')}")
    print(f"  is_short: {t0.get('is_short')}")
    print(f"  exit_reason: {t0.get('exit_reason')}")
    print(f"  stake_amount: {t0.get('stake_amount')}")
    print(f"  Winners: {winners} ({100*winners/len(trades):.1f}%)")
    print(f"  Losers: {losers} ({100*losers/len(trades):.1f}%)")
    print(f"  Avg profit_ratio: {np.mean(profits):.6f}")
    print(f"  Tot profit: {sum(t.get('profit_abs',0) for t in trades):.2f}")
    print()

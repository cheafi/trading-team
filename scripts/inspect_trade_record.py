#!/usr/bin/env python3
"""Inspect first backtest trade record to see available fields."""

import glob
import json
import os
import zipfile

files = sorted(glob.glob("freqtrade/user_data/backtest_results/*.json"))
for f in files[:5]:
    try:
        with zipfile.ZipFile(f, "r") as z:
            name = [n for n in z.namelist() if n.endswith(".json")][0]
            data = json.loads(z.read(name))
    except Exception:
        with open(f) as fh:
            data = json.load(fh)
    strategies = data.get("strategy", data)
    for sname, sdata in strategies.items():
        trades = sdata.get("trades", [])
        if trades:
            print("File:", os.path.basename(f))
            print("Strategy:", sname, "Trades:", len(trades))
            print("Keys:", sorted(trades[0].keys()))
            t = trades[0]
            print("enter_tag:", t.get("enter_tag", "N/A"))
            print("is_short:", t.get("is_short", "N/A"))
            print("open_timestamp:", t.get("open_timestamp", "N/A"))
            break
    else:
        continue
    break

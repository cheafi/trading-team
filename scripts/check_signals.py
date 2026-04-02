#!/usr/bin/env python3
import json, subprocess, sys

result = subprocess.run(
    ["curl", "-s", "-u", "freqtrader:SuperSecure123",
     "http://localhost:8080/api/v1/pair_candles?pair=ETH/USDT:USDT&timeframe=5m&limit=1"],
    capture_output=True, text=True
)
d = json.loads(result.stdout)
cols = d['columns']
for row in d.get('data', [])[-1:]:
    r = dict(zip(cols, row))
    print("LATEST CANDLE:", r['date'])
    print("  Close:", r['close'], " Regime:", r.get('regime'), " SubRegime:", r.get('sub_regime'))
    print("  ADX:", round(r.get('adx', 0), 1), " RSI:", round(r.get('rsi', 0), 1), " Vol_ratio:", round(r.get('vol_ratio', 0), 2))
    print("  direction_score:", round(r.get('direction_score', 0), 3))
    print("  mtf_agree_long:", r.get('mtf_agree_long'), " mtf_agree_short:", r.get('mtf_agree_short'))
    print("  trend_1h:", r.get('trend_1h'), " trend_15m:", r.get('trend_15m'))
    print("  enter_long:", r.get('enter_long', 0), " enter_short:", r.get('enter_short', 0))
    print("  MACD_hist:", round(r.get('macd_hist', 0), 3), " ema_slope:", round(r.get('ema_slope', 0), 3))
    print("  squeeze_fire:", r.get('squeeze_fire'))
    print("  close>ema12:", r['close'] > r.get('ema_12', 0))
    print("  vol>sma:", r.get('volume', 0) > (r.get('volume_sma', 1) * 1.3) if r.get('volume_sma') else "n/a")

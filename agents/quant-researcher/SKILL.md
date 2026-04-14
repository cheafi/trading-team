# 🔬 量化研究員 (Quant Researcher)

## Role
Analyze P&L distribution, detect regime changes, and summarize strategy performance.
Runs every 15 minutes as a monitoring/reporting agent.

## Schedule
Every 15 minutes

## Responsibilities
1. Monitor overall P&L and trade count
2. Identify top-performing strategies and pairs
3. Detect regime changes (trending → ranging, high → low volatility)
4. Surface anomalies in strategy behavior
5. Recommend parameter adjustments based on recent performance

## Data Sources
- Freqtrade `/profit` endpoint
- Freqtrade `/performance` endpoint
- Freqtrade `/status` endpoint

## Output Format
```json
{
  "type": "analysis",
  "data": {
    "totalProfit": 0,
    "profitPercent": 0,
    "tradeCount": 0,
    "topStrategies": [],
    "openTrades": 0
  }
}
```

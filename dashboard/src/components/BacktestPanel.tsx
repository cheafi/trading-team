"use client";

import { useState } from "react";
import { useBacktestResults, triggerBacktest, type BacktestResult } from "@/lib/hooks";

const STRATEGIES = [
  { value: "all", label: "All Strategies" },
  { value: "AdaptiveMLStrategy", label: "AdaptiveML (live)" },
  { value: "A52Strategy", label: "A52 Momentum" },
  { value: "A51Strategy", label: "A51 VWAP" },
  { value: "A31Strategy", label: "A31 Squeeze" },
  { value: "OPTStrategy", label: "OPT Optimized" },
];

const TIMEFRAMES = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
  { value: "1d", label: "1d" },
];

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10).replace(/-/g, "");
}

export function BacktestPanel() {
  const { data: results } = useBacktestResults();
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Default: last 3 months
  const now = new Date();
  const threeMonthsAgo = new Date(now);
  threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3);

  const [startDate, setStartDate] = useState(
    threeMonthsAgo.toISOString().slice(0, 10),
  );
  const [endDate, setEndDate] = useState(now.toISOString().slice(0, 10));
  const [strategy, setStrategy] = useState("AdaptiveMLStrategy");
  const [timeframe, setTimeframe] = useState("5m");

  const handleRun = async () => {
    setRunning(true);
    setMessage(null);
    try {
      const timerange = `${startDate.replace(/-/g, "")}-${endDate.replace(/-/g, "")}`;
      const res = await triggerBacktest({ strategy, timerange, timeframe });
      if (res.error) {
        setMessage(`❌ ${res.error}`);
      } else {
        setMessage(
          `🏃 Running: ${res.strategies?.join(", ")} | ${res.timeframe} | ${res.timerange}`,
        );
      }
    } catch (err: any) {
      setMessage(`❌ ${err.message}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">
        🧪 Backtest Lab
      </h3>

      {/* Controls */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <label className="text-[10px] text-slate-500 uppercase block mb-1">
            Start Date
          </label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-xs text-white font-mono focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase block mb-1">
            End Date
          </label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-xs text-white font-mono focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase block mb-1">
            Strategy
          </label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
          >
            {STRATEGIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase block mb-1">
            Timeframe
          </label>
          <div className="flex gap-1">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={`flex-1 text-[10px] py-1.5 rounded font-mono transition-colors ${
                  timeframe === tf.value
                    ? "bg-blue-600 text-white"
                    : "bg-slate-700 text-slate-400 hover:bg-slate-600"
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Run button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleRun}
          disabled={running}
          className={`px-5 py-2 rounded-lg text-sm font-semibold transition-colors ${
            running
              ? "bg-slate-600 text-slate-400 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-500 text-white"
          }`}
        >
          {running ? "⏳ Running..." : "▶ Run Backtest"}
        </button>
        {message && (
          <span className="text-xs text-slate-400">{message}</span>
        )}
      </div>

      {/* Results table */}
      {results && results.length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide mb-2 block">
            Recent Results ({results.length})
          </span>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1.5 px-2">Strategy</th>
                  <th className="text-left py-1.5 px-2">Range</th>
                  <th className="text-left py-1.5 px-2">TF</th>
                  <th className="text-right py-1.5 px-2">Trades</th>
                  <th className="text-right py-1.5 px-2">Profit %</th>
                  <th className="text-right py-1.5 px-2">Win %</th>
                  <th className="text-right py-1.5 px-2">Max DD</th>
                  <th className="text-right py-1.5 px-2">Sharpe</th>
                  <th className="text-right py-1.5 px-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {results.slice(0, 20).map((r: BacktestResult, i: number) => {
                  const profitColor =
                    r.profit > 0
                      ? "text-emerald-400"
                      : r.profit < 0
                        ? "text-red-400"
                        : "text-slate-400";
                  return (
                    <tr
                      key={`${r.strategy}-${r.timestamp}-${i}`}
                      className="border-b border-slate-700/50 hover:bg-slate-700/30"
                    >
                      <td className="py-1.5 px-2 font-mono text-slate-300">
                        {r.error ? "❌" : ""}{" "}
                        {r.strategy?.replace("Strategy", "")}
                      </td>
                      <td className="py-1.5 px-2 text-slate-500 font-mono">
                        {r.timerange}
                      </td>
                      <td className="py-1.5 px-2 text-slate-500 font-mono">
                        {r.timeframe || "5m"}
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-300">
                        {r.totalTrades}
                      </td>
                      <td
                        className={`py-1.5 px-2 text-right font-mono font-semibold ${profitColor}`}
                      >
                        {r.error
                          ? "ERR"
                          : `${r.profit >= 0 ? "+" : ""}${r.profit.toFixed(2)}%`}
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-300">
                        {r.winRate.toFixed(1)}%
                      </td>
                      <td className="py-1.5 px-2 text-right text-amber-400">
                        {r.maxDrawdown.toFixed(1)}%
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-300">
                        {r.sharpe.toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-600 font-mono">
                        {r.timestamp
                          ? new Date(r.timestamp).toLocaleString("en-GB", {
                              month: "short",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

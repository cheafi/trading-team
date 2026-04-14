"use client";

import { usePerformance } from "@/lib/hooks";

export function PairPerformance() {
  const { data: performance } = usePerformance();

  if (!performance || performance.length === 0) {
    return (
      <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-6 animate-pulse h-48" />
    );
  }

  // Sort by profit descending
  const sorted = [...performance].sort((a, b) => b.profit - a.profit);
  const maxProfit = Math.max(...sorted.map((p) => Math.abs(p.profit)), 0.01);

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300">
          🏆 Pair Performance
        </h3>
        <span className="text-[10px] text-slate-500">
          {sorted.length} pairs
        </span>
      </div>

      <div className="space-y-2">
        {sorted.map((pair) => {
          const name = pair.pair?.replace("/USDT:USDT", "") || "—";
          const isPositive = pair.profit >= 0;
          const barWidth = Math.min(
            (Math.abs(pair.profit) / maxProfit) * 100,
            100
          );

          return (
            <div key={pair.pair} className="group">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-white w-10">
                    {name}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {pair.count} trades
                  </span>
                </div>
                <span
                  className={`text-xs font-mono font-bold ${
                    isPositive ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {isPositive ? "+" : ""}
                  {pair.profit.toFixed(2)}%
                </span>
              </div>
              <div className="w-full h-1.5 bg-slate-700/30 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    isPositive
                      ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                      : "bg-gradient-to-r from-red-500 to-red-400"
                  }`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

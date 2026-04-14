"use client";

import { usePerformance, useFunding } from "@/lib/hooks";

export function PairPerformance() {
  const { data: performance } = usePerformance();
  const { data: funding } = useFunding();

  if (!performance || performance.length === 0) {
    return (
      <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-6 animate-pulse h-48" />
    );
  }

  // Build funding rate lookup: "ETH/USDT:USDT" → rate
  const frMap: Record<string, number> = {};
  if (funding) {
    for (const f of funding) {
      frMap[f.pair] = f.fundingRate;
    }
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
          const fr = frMap[pair.pair];
          const hasFR = fr !== undefined && fr !== null;
          // Positive FR = longs pay shorts (good for shorts)
          // Negative FR = shorts pay longs (bad for shorts)
          const frPositive = hasFR && fr >= 0;

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
                  {hasFR && (
                    <span
                      className={`text-[9px] font-mono px-1 py-0.5 rounded ${
                        frPositive
                          ? "bg-emerald-900/40 text-emerald-400"
                          : "bg-red-900/40 text-red-400"
                      }`}
                      title={`Funding rate: ${(fr * 100).toFixed(4)}% — ${
                        frPositive
                          ? "longs pay shorts ✓"
                          : "shorts pay longs ✗"
                      }`}
                    >
                      FR {(fr * 100).toFixed(3)}%
                    </span>
                  )}
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

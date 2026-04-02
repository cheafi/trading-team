"use client";

import { useStrategies } from "@/lib/hooks";

const STRATEGY_META: Record<
  string,
  { c: number; e: number; tf: string; desc: string }
> = {
  AdaptiveMLStrategy: { c: 0.5, e: 0.0, tf: "5m", desc: "🧠 ML自適應" },
  A52Strategy: { c: 0.5, e: -0.18, tf: "5m", desc: "多因子動量" },
  OPTStrategy: { c: 0.65, e: 0.05, tf: "5m", desc: "趨勢跟蹤" },
  A51Strategy: { c: 0.35, e: 0.0, tf: "5m", desc: "VWAP 剝頭皮" },
  A31Strategy: { c: 0.8, e: -0.1, tf: "5m", desc: "波動突破" },
};

export function StrategyRanking() {
  const { data } = useStrategies();
  const profit = data?.profit;

  // Build strategy data from performance + meta
  const strategies = Object.entries(STRATEGY_META).map(
    ([name, meta], idx) => {
      const perf = data?.performance?.find((p) =>
        p.pair?.includes(name)
      );
      return {
        rank: idx + 1,
        name: name.replace("Strategy", ""),
        ...meta,
        profit: perf?.profit ?? 0,
        trades: perf?.count ?? 0,
        wrPct:
          profit && profit.trade_count > 0
            ? (
                ((profit.winning_trades || 0) /
                  (profit.trade_count || 1)) *
                100
              ).toFixed(1)
            : "—",
        ddPct: profit?.max_drawdown != null
            ? ((profit.max_drawdown ?? 0) * 100).toFixed(1)
            : "—",
      };
    }
  );

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-3 text-slate-400 font-medium text-xs">
                #
              </th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium text-xs">
                策略
              </th>
              <th className="text-center px-4 py-3 text-slate-400 font-medium text-xs">
                TF
              </th>
              <th className="text-center px-4 py-3 text-slate-400 font-medium text-xs">
                c
              </th>
              <th className="text-center px-4 py-3 text-slate-400 font-medium text-xs">
                e
              </th>
              <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                WR%
              </th>
              <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                DD%
              </th>
              <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                利潤
              </th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr
                key={s.name}
                className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
              >
                <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">
                  {s.rank}
                </td>
                <td className="px-4 py-2.5">
                  <div>
                    <span className="text-white font-semibold text-xs">
                      {s.name}
                    </span>
                    <span className="text-slate-500 text-[10px] ml-2">
                      {s.desc}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-2.5 text-center text-slate-400 font-mono text-xs">
                  {s.tf}
                </td>
                <td className="px-4 py-2.5 text-center text-blue-400 font-mono text-xs">
                  {s.c.toFixed(2)}
                </td>
                <td className="px-4 py-2.5 text-center font-mono text-xs">
                  <span
                    className={
                      s.e < 0
                        ? "text-red-400"
                        : s.e > 0
                          ? "text-green-400"
                          : "text-slate-400"
                    }
                  >
                    {s.e >= 0 ? "+" : ""}
                    {s.e.toFixed(2)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right text-emerald-400 font-mono text-xs">
                  {s.wrPct}%
                </td>
                <td className="px-4 py-2.5 text-right text-yellow-400 font-mono text-xs">
                  {s.ddPct}%
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs">
                  <span
                    className={
                      s.profit > 0 ? "text-emerald-400" : "text-red-400"
                    }
                  >
                    {s.profit > 0 ? "+" : ""}
                    {s.profit.toFixed(2)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

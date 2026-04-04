"use client";

import { useMLHistory, useMLState } from "@/lib/hooks";

export function StrategyRanking() {
  const { data: history } = useMLHistory();
  const { data: ml } = useMLState();

  // Use the latest training log entry for real strategy metrics
  const latest =
    history && history.length > 0 ? history[history.length - 1] : null;
  const stratScores = latest?.strategy_scores || {};

  const strategies = Object.entries(stratScores)
    .map(([name, scores], idx) => ({
      rank: idx + 1,
      name: name.replace("Strategy", ""),
      winRate: scores.win_rate ?? 0,
      profitFactor: scores.profit_factor ?? 0,
      sharpe: scores.sharpe ?? 0,
      score: scores.score ?? 0,
      totalProfit: scores.total_profit ?? 0,
    }))
    .sort((a, b) => b.score - a.score)
    .map((s, i) => ({ ...s, rank: i + 1 }));

  // Active strategy from ML state
  const activeStrategy = ml?.strategy || "—";

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 overflow-hidden">
      {strategies.length === 0 ? (
        <div className="p-6 text-center text-slate-500 text-sm">
          No ML training data yet. Run ml_optimizer.py to generate.
        </div>
      ) : (
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
                <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                  WR%
                </th>
                <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                  PF
                </th>
                <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                  Sharpe
                </th>
                <th className="text-right px-4 py-3 text-slate-400 font-medium text-xs">
                  Score
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
                  className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                    activeStrategy === s.name ? "bg-blue-500/5" : ""
                  }`}
                >
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">
                    {s.rank}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-white font-semibold text-xs">
                      {s.name}
                    </span>
                    {activeStrategy === s.name && (
                      <span className="text-blue-400 text-[10px] ml-2">
                        ● active
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-emerald-400 font-mono text-xs">
                    {(s.winRate * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2.5 text-right text-blue-400 font-mono text-xs">
                    {s.profitFactor.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs">
                    <span
                      className={
                        s.sharpe > 0 ? "text-emerald-400" : "text-red-400"
                      }
                    >
                      {s.sharpe.toFixed(2)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-purple-400 font-mono text-xs">
                    {s.score.toFixed(3)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs">
                    <span
                      className={
                        s.totalProfit > 0 ? "text-emerald-400" : "text-red-400"
                      }
                    >
                      {s.totalProfit > 0 ? "+" : ""}
                      {s.totalProfit.toFixed(4)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

"use client";

import { useProfit } from "@/lib/hooks";

export function EquityMini() {
  const { data: profit } = useProfit();

  // Generate a simple equity curve from available data
  const totalProfit = profit?.profit_all_coin ?? 0;
  const wins = profit?.winning_trades ?? 0;
  const losses = profit?.losing_trades ?? 0;
  const total = wins + losses;

  if (total === 0) {
    return (
      <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-3">
          📈 資產曲線 Equity
        </h3>
        <div className="text-center py-4 text-slate-500 text-sm">
          No trade data yet
        </div>
      </div>
    );
  }

  const isPositive = totalProfit >= 0;
  const winRate = total > 0 ? ((wins / total) * 100).toFixed(1) : "0";
  const avgPerTrade = total > 0 ? totalProfit / total : 0;
  const closedProfit = profit?.profit_closed_coin ?? 0;
  const maxDDPct = (profit?.max_drawdown ?? 0) * 100;
  const maxDD = profit?.max_drawdown_abs ?? 0;

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300">
          📈 交易統計 Trade Stats
        </h3>
        <span className={`text-lg font-mono font-bold ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
          {isPositive ? "+" : ""}{totalProfit.toFixed(2)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-0.5">勝率 Win Rate</p>
          <p className="text-lg font-mono font-bold text-emerald-400">{winRate}%</p>
          <p className="text-[10px] text-slate-600">{wins}W / {losses}L</p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-0.5">均利 Avg/Trade</p>
          <p className={`text-lg font-mono font-bold ${avgPerTrade >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {avgPerTrade >= 0 ? "+" : ""}{avgPerTrade.toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-600">USDT per trade</p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-0.5">已實現 Closed</p>
          <p className={`text-lg font-mono font-bold ${closedProfit >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {closedProfit >= 0 ? "+" : ""}{closedProfit.toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-600">USDT realized</p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-0.5">回撤 Max DD</p>
          <p className="text-lg font-mono font-bold text-yellow-400">
            {maxDDPct.toFixed(2)}%
          </p>
          <p className="text-[10px] text-slate-600">{maxDD.toFixed(2)} USDT</p>
        </div>
      </div>

      {/* Win/Loss Visual Bar */}
      <div className="mt-3">
        <div className="flex items-center gap-1 h-3 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-l-full transition-all"
            style={{ width: `${total > 0 ? (wins / total) * 100 : 50}%` }}
          />
          <div
            className="h-full bg-red-500 rounded-r-full transition-all"
            style={{ width: `${total > 0 ? (losses / total) * 100 : 50}%` }}
          />
        </div>
        <div className="flex justify-between text-[9px] text-slate-600 mt-1">
          <span>✅ {wins} wins ({winRate}%)</span>
          <span>❌ {losses} losses</span>
        </div>
      </div>
    </div>
  );
}

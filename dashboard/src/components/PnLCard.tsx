"use client";

import { useProfit, useTrades } from "@/lib/hooks";
import { PnLSkeleton } from "@/components/Skeleton";

export function PnLCard() {
  const { data: profit, isLoading, error } = useProfit();
  const { data: trades } = useTrades();

  if (isLoading) return <PnLSkeleton />;

  const connected = !error && profit !== undefined;
  const totalProfit = profit?.profit_all_coin ?? 0;
  const totalProfitPct = profit?.profit_all_percent ?? 0;
  const openTrades = Array.isArray(trades) ? trades.length : 0;
  const closedTrades = profit?.closed_trade_count ?? 0;
  const wins = profit?.winning_trades ?? 0;
  const losses = profit?.losing_trades ?? 0;
  const total = profit?.trade_count ?? 0;

  const isPositive = totalProfit >= 0;
  const winRate = total > 0 ? ((wins / total) * 100).toFixed(1) : "—";
  const profitFactor = profit?.profit_factor
    ? profit.profit_factor.toFixed(2)
    : wins > 0 ? "∞" : "—";

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300">
          💰 P&L Overview
        </h3>
        <div className="flex items-center gap-2">
          {!connected && (
            <span className="text-[10px] text-red-400 font-semibold">⚠ {isLoading ? "Loading..." : "Disconnected"}</span>
          )}
          {connected && (
            <>
              <span className="text-[10px] text-slate-500">
                {openTrades} open
              </span>
              <span className="text-[10px] text-slate-600">|</span>
              <span className="text-[10px] text-slate-500">
                {closedTrades} closed
              </span>
            </>
          )}
        </div>
      </div>

      {/* Big P&L Number */}
      <div className="mb-3">
        <p
          className={`text-3xl font-bold font-mono ${
            !connected ? "text-slate-600" : isPositive ? "text-emerald-400" : "text-red-400"
          }`}
        >
          {!connected ? "—" : `${isPositive ? "+" : ""}${totalProfit.toFixed(2)}`}
          <span className="text-lg ml-1 opacity-70">USDT</span>
        </p>
        <p
          className={`text-sm font-mono ${
            isPositive ? "text-emerald-400/60" : "text-red-400/60"
          }`}
        >
          {isPositive ? "+" : ""}
          {totalProfitPct.toFixed(2)}%
        </p>
      </div>

      {/* Quick Stats Row */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-[#111827] rounded-lg p-2 border border-slate-700/50 text-center">
          <p className="text-[9px] text-slate-500">WR</p>
          <p className="text-sm font-mono font-bold text-emerald-400">{winRate}%</p>
        </div>
        <div className="bg-[#111827] rounded-lg p-2 border border-slate-700/50 text-center">
          <p className="text-[9px] text-slate-500">PF</p>
          <p className="text-sm font-mono font-bold text-blue-400">{profitFactor}</p>
        </div>
        <div className="bg-[#111827] rounded-lg p-2 border border-slate-700/50 text-center">
          <p className="text-[9px] text-slate-500">W/L</p>
          <p className="text-sm font-mono font-bold">
            <span className="text-emerald-400">{wins}</span>
            <span className="text-slate-600">/</span>
            <span className="text-red-400">{losses}</span>
          </p>
        </div>
      </div>
    </div>
  );
}

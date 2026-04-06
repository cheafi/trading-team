"use client";

import { useProfit, useTrades, useMLState } from "@/lib/hooks";

export function TeamHeader() {
  const { data: profit } = useProfit();
  const { data: trades } = useTrades();
  const { data: ml } = useMLState();

  const totalProfit = profit?.profit_all_coin ?? 0;
  const isPositive = totalProfit >= 0;
  const openCount = Array.isArray(trades) ? trades.length : 0;
  const regime = ml?.regime || "—";
  const regimeEmoji: Record<string, string> = {
    TRENDING_UP: "📈",
    TRENDING_DOWN: "📉",
    RANGING: "↔️",
    VOLATILE: "⚡",
  };

  return (
    <header className="mb-6 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="text-4xl">🐼</div>
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            CC
          </h1>
          <p className="text-sm text-slate-400">
            USDT Futures • 5m R2 Short Specialist • Paper Trading
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {/* Live P&L badge */}
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
          isPositive
            ? "bg-emerald-500/10 border-emerald-500/20"
            : "bg-red-500/10 border-red-500/20"
        }`}>
          <span className={`text-xs font-mono font-bold ${
            isPositive ? "text-emerald-400" : "text-red-400"
          }`}>
            {isPositive ? "+" : ""}{totalProfit.toFixed(2)} USDT
          </span>
        </div>
        {/* Regime badge */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20">
          <span className="text-xs">{regimeEmoji[regime] || "❓"}</span>
          <span className="text-[10px] text-purple-300 font-medium">{regime}</span>
        </div>
        {/* Open trades */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/20">
          <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse-dot" />
          <span className="text-xs text-blue-400 font-medium">
            {openCount > 0 ? `${openCount} OPEN` : "IDLE"}
          </span>
        </div>
        <div className="text-xs text-slate-500 font-mono">
          {new Date().toLocaleDateString("en-CA")} UTC
        </div>
      </div>
    </header>
  );
}

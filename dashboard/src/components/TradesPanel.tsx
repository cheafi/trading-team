"use client";

import { useTrades } from "@/lib/hooks";

export function TradesPanel() {
  const { data: trades } = useTrades();

  if (!trades || trades.length === 0) {
    return (
      <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-300">
            📋 持倉列表 Open Trades
          </h3>
          <span className="text-[10px] px-2 py-1 rounded-full bg-slate-700/50 text-slate-400">
            0 positions
          </span>
        </div>
        <div className="text-center py-8">
          <p className="text-3xl mb-2">😴</p>
          <p className="text-sm text-slate-500">目前無持倉 No open positions</p>
          <p className="text-[10px] text-slate-600 mt-1">Strategy waiting for R2 ranging setup...</p>
        </div>
      </div>
    );
  }

  const totalPnl = trades.reduce(
    (sum: number, t: any) => sum + (t.profit_abs || 0),
    0
  );

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300">
          📋 持倉列表 Open Trades
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-[10px] px-2 py-1 rounded-full bg-blue-500/20 text-blue-300">
            {trades.length} open
          </span>
          <span
            className={`text-xs font-mono font-bold ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
          >
            {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)} USDT
          </span>
        </div>
      </div>

      <div className="space-y-2">
        {trades.map((trade: any, idx: number) => {
          const isShort = trade.is_short;
          const profitPct = trade.profit_pct || 0;
          const profitAbs = trade.profit_abs || 0;
          const isWinning = profitPct >= 0;

          return (
            <div
              key={trade.trade_id || idx}
              className={`rounded-lg border p-3 transition-all ${
                isWinning
                  ? "border-emerald-500/20 bg-emerald-500/5"
                  : "border-red-500/20 bg-red-500/5"
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                      isShort
                        ? "bg-red-500/20 text-red-300"
                        : "bg-emerald-500/20 text-emerald-300"
                    }`}
                  >
                    {isShort ? "SHORT" : "LONG"}
                  </span>
                  <span className="text-sm font-semibold text-white">
                    {trade.pair?.replace("/USDT:USDT", "") || "—"}
                  </span>
                </div>
                <span
                  className={`text-sm font-mono font-bold ${
                    isWinning ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {profitPct >= 0 ? "+" : ""}{profitPct.toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>
                  {trade.enter_tag || "—"} • {trade.trade_duration || "—"}
                </span>
                <span className={`font-mono ${isWinning ? "text-emerald-400/70" : "text-red-400/70"}`}>
                  {profitAbs >= 0 ? "+" : ""}{profitAbs.toFixed(2)} USDT
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

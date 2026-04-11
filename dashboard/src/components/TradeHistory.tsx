"use client";

import { useTradeHistory } from "@/lib/hooks";

export function TradeHistory() {
  const { data, isLoading } = useTradeHistory(50);

  const trades = data?.trades || [];
  const count = data?.trades_count || 0;

  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-1/4 mb-3" />
        <div className="h-40 bg-slate-700 rounded" />
      </div>
    );
  }

  if (!trades.length) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <h3 className="text-sm font-semibold text-slate-300 mb-3">
          📜 Trade History
        </h3>
        <p className="text-xs text-slate-500 text-center py-6">
          No closed trades yet — strategy is waiting for R2 setups.
        </p>
      </div>
    );
  }

  // Summary stats
  const totalPnl = trades.reduce(
    (s: number, t: any) => s + (t.profit_abs || 0),
    0,
  );
  const wins = trades.filter((t: any) => (t.profit_abs || t.close_profit || 0) > 0).length;
  const losses = trades.length - wins;
  const winRate = trades.length > 0 ? ((wins / trades.length) * 100).toFixed(1) : "0.0";
  const avgDuration = trades.reduce((s: number, t: any) => {
    if (!t.open_date || !t.close_date) return s;
    return s + (new Date(t.close_date).getTime() - new Date(t.open_date).getTime());
  }, 0) / (trades.length || 1);
  const avgDurMin = Math.round(avgDuration / 60000);

  // Exit reason breakdown
  const exitReasons: Record<string, number> = {};
  for (const t of trades) {
    const r = t.exit_reason || "unknown";
    exitReasons[r] = (exitReasons[r] || 0) + 1;
  }

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">
          📜 Trade History
        </h3>
        <span className="text-[10px] text-slate-500">
          {count} total closed
        </span>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase">
            Total P&L
          </span>
          <span
            className={`text-sm font-mono font-bold ${
              totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {totalPnl >= 0 ? "+" : ""}
            {totalPnl.toFixed(2)} USDT
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase">Win Rate</span>
          <span
            className={`text-sm font-mono font-bold ${
              parseFloat(winRate) >= 50
                ? "text-emerald-400"
                : "text-amber-400"
            }`}
          >
            {winRate}%
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase">W / L</span>
          <span className="text-sm font-mono">
            <span className="text-emerald-400">{wins}</span>
            <span className="text-slate-600"> / </span>
            <span className="text-red-400">{losses}</span>
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase">
            Avg Duration
          </span>
          <span className="text-sm font-mono text-slate-300">
            {avgDurMin < 60
              ? `${avgDurMin}m`
              : `${Math.floor(avgDurMin / 60)}h ${avgDurMin % 60}m`}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase">
            Exit Reasons
          </span>
          <div className="flex flex-wrap gap-1 mt-0.5">
            {Object.entries(exitReasons)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 4)
              .map(([reason, cnt]) => (
                <span
                  key={reason}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400"
                >
                  {reason}: {cnt}
                </span>
              ))}
          </div>
        </div>
      </div>

      {/* Trade table */}
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-800">
            <tr className="text-slate-500 border-b border-slate-700">
              <th className="text-left py-1.5 px-1.5">#</th>
              <th className="text-left py-1.5 px-1.5">Pair</th>
              <th className="text-left py-1.5 px-1.5">Side</th>
              <th className="text-right py-1.5 px-1.5">Entry</th>
              <th className="text-right py-1.5 px-1.5">Exit</th>
              <th className="text-right py-1.5 px-1.5">P&L %</th>
              <th className="text-right py-1.5 px-1.5">P&L $</th>
              <th className="text-left py-1.5 px-1.5">Exit Reason</th>
              <th className="text-right py-1.5 px-1.5">Duration</th>
              <th className="text-left py-1.5 px-1.5">Opened</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t: any, i: number) => {
              const pnlPct = (t.profit_pct || t.close_profit * 100 || 0);
              const pnlAbs = t.profit_abs || 0;
              const isWin = pnlAbs > 0;
              const dur =
                t.open_date && t.close_date
                  ? Math.round(
                      (new Date(t.close_date).getTime() -
                        new Date(t.open_date).getTime()) /
                        60000,
                    )
                  : 0;

              return (
                <tr
                  key={t.trade_id || i}
                  className={`border-b border-slate-700/30 hover:bg-slate-700/20 ${
                    isWin ? "" : "bg-red-500/5"
                  }`}
                >
                  <td className="py-1 px-1.5 text-slate-600 font-mono">
                    {t.trade_id || i + 1}
                  </td>
                  <td className="py-1 px-1.5 font-mono text-slate-300">
                    {(t.pair || "").replace("/USDT:USDT", "")}
                  </td>
                  <td className="py-1 px-1.5">
                    <span
                      className={`text-[9px] font-bold px-1 py-0.5 rounded ${
                        t.is_short
                          ? "bg-red-500/20 text-red-300"
                          : "bg-emerald-500/20 text-emerald-300"
                      }`}
                    >
                      {t.is_short ? "SHORT" : "LONG"}
                    </span>
                  </td>
                  <td className="py-1 px-1.5 text-right font-mono text-slate-400">
                    {(t.open_rate || 0).toPrecision(5)}
                  </td>
                  <td className="py-1 px-1.5 text-right font-mono text-slate-400">
                    {(t.close_rate || 0).toPrecision(5)}
                  </td>
                  <td
                    className={`py-1 px-1.5 text-right font-mono font-semibold ${
                      isWin ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {pnlPct >= 0 ? "+" : ""}
                    {pnlPct.toFixed(2)}%
                  </td>
                  <td
                    className={`py-1 px-1.5 text-right font-mono ${
                      isWin ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {pnlAbs >= 0 ? "+" : ""}
                    {pnlAbs.toFixed(2)}
                  </td>
                  <td className="py-1 px-1.5 text-slate-400">
                    {t.exit_reason || "—"}
                  </td>
                  <td className="py-1 px-1.5 text-right font-mono text-slate-500">
                    {dur < 60
                      ? `${dur}m`
                      : `${Math.floor(dur / 60)}h${dur % 60}m`}
                  </td>
                  <td className="py-1 px-1.5 text-slate-600 font-mono">
                    {t.open_date
                      ? new Date(t.open_date).toLocaleDateString("en-GB", {
                          month: "short",
                          day: "2-digit",
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
  );
}

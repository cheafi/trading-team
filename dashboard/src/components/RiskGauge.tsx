"use client";

import { useProfit } from "@/lib/hooks";

export function RiskGauge() {
  const { data: profit } = useProfit();

  const dd = (profit?.max_drawdown ?? 0) * 100;
  const riskLevel =
    dd > 20
      ? "CRITICAL"
      : dd > 15
        ? "HIGH"
        : dd > 10
          ? "MEDIUM"
          : "LOW";

  const riskColor =
    riskLevel === "CRITICAL"
      ? "text-red-400"
      : riskLevel === "HIGH"
        ? "text-orange-400"
        : riskLevel === "MEDIUM"
          ? "text-yellow-400"
          : "text-emerald-400";

  const barColor =
    riskLevel === "CRITICAL"
      ? "bg-red-500"
      : riskLevel === "HIGH"
        ? "bg-orange-500"
        : riskLevel === "MEDIUM"
          ? "bg-yellow-500"
          : "bg-emerald-500";

  const badgeBg =
    riskLevel === "CRITICAL" ? "bg-red-500/20"
    : riskLevel === "HIGH" ? "bg-orange-500/20"
    : riskLevel === "MEDIUM" ? "bg-yellow-500/20"
    : "bg-emerald-500/20";

  const barWidth = Math.min(dd / 25 * 100, 100);

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300">
          🛡️ 風險控制
        </h3>
        <span
          className={`text-xs font-bold px-2 py-1 rounded ${riskColor} ${badgeBg}`}
        >
          {riskLevel}
        </span>
      </div>

      {/* Drawdown bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-slate-400">最大回撤 Max DD</span>
          <span className={`font-mono ${riskColor}`}>
            {dd.toFixed(1)}%
          </span>
        </div>
        <div className="w-full bg-slate-700/50 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-slate-600 mt-1">
          <span>0%</span>
          <span className="text-yellow-500/50">15%</span>
          <span className="text-red-500/50">25%</span>
        </div>
      </div>

      {/* Risk metrics */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] text-slate-500 mb-0.5">勝率 WR</p>
          <p className="text-sm font-mono text-emerald-400">
            {profit?.winrate != null
              ? (profit.winrate * 100).toFixed(1)
              : "—"}
            %
          </p>
        </div>
        <div>
          <p className="text-[10px] text-slate-500 mb-0.5">
            盈虧比 PF
          </p>
          <p className="text-sm font-mono text-blue-400">
            {profit?.profit_factor
              ? profit.profit_factor.toFixed(2)
              : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}

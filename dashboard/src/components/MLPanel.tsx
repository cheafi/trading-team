"use client";

import { useMLState, useMLHistory } from "@/lib/hooks";

const REGIME_COLORS: Record<string, string> = {
  TRENDING_UP: "text-emerald-400",
  TRENDING_DOWN: "text-red-400",
  RANGING: "text-blue-400",
  VOLATILE: "text-yellow-400",
  HIGH_VOLATILITY: "text-yellow-400",
  unknown: "text-slate-400",
};

const REGIME_EMOJI: Record<string, string> = {
  TRENDING_UP: "📈",
  TRENDING_DOWN: "📉",
  RANGING: "↔️",
  VOLATILE: "⚡",
  HIGH_VOLATILITY: "⚡",
  unknown: "❓",
};

const TREND_DISPLAY: Record<string, { text: string; color: string }> = {
  improving: { text: "↗ 改善中", color: "text-emerald-400" },
  degrading: { text: "↘ 退化中", color: "text-red-400" },
  stable: { text: "→ 穩定", color: "text-slate-400" },
};

export function MLPanel() {
  const { data: ml } = useMLState();
  const { data: history } = useMLHistory();

  const regime = ml?.regime || "unknown";
  const regimeColor = REGIME_COLORS[regime] || "text-slate-400";
  const regimeEmoji = REGIME_EMOJI[regime] || "❓";
  const trend = TREND_DISPLAY[ml?.improvementTrend || "stable"] || TREND_DISPLAY.stable;

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <span>🧠</span> ML 自適應引擎
        </h3>
        <span className="text-[10px] text-slate-500">
          {ml?.lastTrained
            ? `上次訓練: ${new Date(ml.lastTrained).toLocaleString("zh-TW")}`
            : "尚未訓練"}
        </span>
      </div>

      {/* Active Regime */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">當前市場</p>
          <p className={`text-sm font-bold ${regimeColor}`}>
            {regimeEmoji} {regime}
          </p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">啟用策略</p>
          <p className="text-sm font-bold text-blue-400">
            {ml?.strategy || "—"}
          </p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">學習趨勢</p>
          <p className={`text-sm font-bold ${trend.color}`}>
            {trend.text}
          </p>
        </div>
      </div>

      {/* Regime Params Table */}
      {ml?.params && (
        <div className="mb-4">
          <p className="text-[10px] text-slate-500 mb-2">
            各市場最優參數 Optimal Params per Regime
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/50">
                  <th className="text-left py-1 px-2">Regime</th>
                  <th className="text-center py-1 px-2">Strategy</th>
                  <th className="text-center py-1 px-2">c</th>
                  <th className="text-center py-1 px-2">e</th>
                  <th className="text-right py-1 px-2">WR%</th>
                  <th className="text-right py-1 px-2">Sharpe</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(ml.params).map(([rid, p]) => {
                  const rNames: Record<string, string> = {
                    "0": "📈 Trend ↑",
                    "1": "📉 Trend ↓",
                    "2": "↔️ Range",
                    "3": "⚡ Volatile",
                  };
                  return (
                    <tr
                      key={rid}
                      className="border-b border-slate-800/30 hover:bg-slate-800/20"
                    >
                      <td className="py-1.5 px-2 text-slate-300">
                        {rNames[rid] || `R${rid}`}
                      </td>
                      <td className="py-1.5 px-2 text-center text-blue-400 font-mono">
                        {p.strategy}
                      </td>
                      <td className="py-1.5 px-2 text-center text-cyan-400 font-mono">
                        {(p.c ?? 0).toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2 text-center font-mono">
                        <span
                          className={
                            (p.e ?? 0) < 0
                              ? "text-red-400"
                              : (p.e ?? 0) > 0
                                ? "text-green-400"
                                : "text-slate-400"
                          }
                        >
                          {(p.e ?? 0) >= 0 ? "+" : ""}
                          {(p.e ?? 0).toFixed(2)}
                        </span>
                      </td>
                      <td className="py-1.5 px-2 text-right text-emerald-400 font-mono">
                        {((p.win_rate ?? 0) * 100).toFixed(1)}%
                      </td>
                      <td className="py-1.5 px-2 text-right text-yellow-400 font-mono">
                        {(p.sharpe ?? 0).toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Training History Sparkline */}
      {history && history.length > 0 && (
        <div>
          <p className="text-[10px] text-slate-500 mb-2">
            訓練歷史 Training History ({history.length} runs)
          </p>
          <div className="flex items-end gap-[2px] h-8">
            {history.slice(-30).map((entry, idx) => {
              const scores = Object.values(entry.strategy_scores || {});
              const avgScore =
                scores.reduce((s, e) => s + (e.score || 0), 0) /
                (scores.length || 1);
              const barHeight = Math.max(avgScore * 100, 5);
              const color =
                avgScore > 0.6
                  ? "bg-emerald-500"
                  : avgScore > 0.4
                    ? "bg-yellow-500"
                    : "bg-red-500";
              return (
                <div
                  key={idx}
                  className={`flex-1 rounded-sm ${color} opacity-80 hover:opacity-100 transition-opacity`}
                  style={{ height: `${barHeight}%` }}
                  title={`Score: ${avgScore.toFixed(3)} | ${new Date(entry.timestamp).toLocaleDateString("zh-TW")}`}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

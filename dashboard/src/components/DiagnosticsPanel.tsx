"use client";

import { useRejections } from "@/lib/hooks";

export function DiagnosticsPanel() {
  const { data: rejections } = useRejections(100);

  // ── Breakdowns ──
  const reasonCounts: Record<string, number> = {};
  const pairCounts: Record<string, number> = {};
  const hourCounts: Record<number, number> = {};
  const regimeCounts: Record<string, number> = {};
  const sideCounts: Record<string, number> = {};

  for (const r of rejections || []) {
    reasonCounts[r.reason] = (reasonCounts[r.reason] || 0) + 1;

    const pair = (r as any).pair || "unknown";
    pairCounts[pair] = (pairCounts[pair] || 0) + 1;

    const regime = (r as any).regime || "—";
    regimeCounts[regime] = (regimeCounts[regime] || 0) + 1;

    const side = r.side || "unknown";
    sideCounts[side] = (sideCounts[side] || 0) + 1;

    if (r.timestamp) {
      const h = new Date(r.timestamp).getUTCHours();
      hourCounts[h] = (hourCounts[h] || 0) + 1;
    }
  }

  const sortedReasons = Object.entries(reasonCounts).sort(
    (a, b) => b[1] - a[1],
  );
  const sortedPairs = Object.entries(pairCounts).sort((a, b) => b[1] - a[1]);
  const totalRejections = rejections?.length || 0;
  const maxHourCount = Math.max(1, ...Object.values(hourCounts));

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <span>🚫</span> Trade Rejections
        </h3>
        <span className="text-xs text-slate-500">
          {totalRejections} entries
        </span>
      </div>

      {totalRejections === 0 ? (
        <p className="text-xs text-slate-500 italic text-center py-4">
          No rejections logged yet — the strategy hasn't rejected any trades.
        </p>
      ) : (
        <>
          {/* Top row: reason + pair breakdown */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Reason breakdown */}
            <div>
              <span className="text-[10px] text-slate-500 uppercase mb-1.5 block">
                Rejection Reasons
              </span>
              <div className="space-y-1">
                {sortedReasons.slice(0, 8).map(([reason, count]) => {
                  const pct = (count / totalRejections) * 100;
                  return (
                    <div key={reason} className="flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between text-[10px] mb-0.5">
                          <span className="text-slate-400 truncate">
                            {reason}
                          </span>
                          <span className="text-slate-500 ml-1 shrink-0">
                            {count} ({pct.toFixed(0)}%)
                          </span>
                        </div>
                        <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-red-500/60 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Pair breakdown */}
            <div>
              <span className="text-[10px] text-slate-500 uppercase mb-1.5 block">
                By Pair
              </span>
              <div className="space-y-1">
                {sortedPairs.map(([pair, count]) => {
                  const pct = (count / totalRejections) * 100;
                  return (
                    <div key={pair} className="flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between text-[10px] mb-0.5">
                          <span className="text-slate-400 font-mono">
                            {pair.replace("/USDT:USDT", "")}
                          </span>
                          <span className="text-slate-500 ml-1 shrink-0">
                            {count}
                          </span>
                        </div>
                        <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-amber-500/60 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Side + Regime pills */}
              <div className="flex flex-wrap gap-1.5 mt-3">
                {Object.entries(sideCounts).map(([side, cnt]) => (
                  <span
                    key={side}
                    className={`text-[9px] px-1.5 py-0.5 rounded-full border ${
                      side === "short"
                        ? "bg-red-500/10 text-red-300 border-red-500/20"
                        : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                    }`}
                  >
                    {side}: {cnt}
                  </span>
                ))}
                {Object.entries(regimeCounts).map(([regime, cnt]) => (
                  <span
                    key={regime}
                    className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-300 border border-blue-500/20"
                  >
                    R{regime}: {cnt}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Hour heatmap */}
          <div>
            <span className="text-[10px] text-slate-500 uppercase mb-1.5 block">
              Rejections by Hour (UTC)
            </span>
            <div className="flex gap-[2px] items-end h-10">
              {Array.from({ length: 24 }, (_, h) => {
                const cnt = hourCounts[h] || 0;
                const height =
                  cnt > 0 ? Math.max(8, (cnt / maxHourCount) * 100) : 4;
                const intensity =
                  cnt === 0
                    ? "bg-slate-700"
                    : cnt / maxHourCount > 0.7
                      ? "bg-red-500"
                      : cnt / maxHourCount > 0.3
                        ? "bg-amber-500"
                        : "bg-blue-500/60";
                return (
                  <div
                    key={h}
                    className="flex-1 flex flex-col items-center gap-0.5"
                  >
                    <div
                      className={`w-full rounded-sm ${intensity}`}
                      style={{ height: `${height}%` }}
                      title={`${h}:00 UTC — ${cnt} rejections`}
                    />
                    {h % 4 === 0 && (
                      <span className="text-[8px] text-slate-600">{h}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent rejections log */}
          <div>
            <span className="text-[10px] text-slate-500 uppercase mb-1 block">
              Recent Rejections
            </span>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {(rejections || []).slice(0, 30).map((r, i) => (
                <div
                  key={`${r.timestamp}-${i}`}
                  className="flex items-center gap-2 text-[11px]"
                >
                  <span className="text-slate-600 font-mono w-12 shrink-0">
                    {r.timestamp
                      ? new Date(r.timestamp).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                          timeZone: "UTC",
                        })
                      : "—"}
                  </span>
                  <span className="text-slate-500 font-mono w-10 shrink-0">
                    {((r as any).pair || "")
                      .replace("/USDT:USDT", "")
                      .slice(0, 5)}
                  </span>
                  <span
                    className={`w-10 shrink-0 font-semibold ${
                      r.side === "short" ? "text-red-400" : "text-emerald-400"
                    }`}
                  >
                    {r.side?.toUpperCase() || "—"}
                  </span>
                  <span className="text-slate-400 truncate flex-1">
                    {r.reason}
                  </span>
                  <span className="text-slate-600 shrink-0">
                    R{(r as any).regime || "?"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

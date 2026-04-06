"use client";

import { useRejections } from "@/lib/hooks";

export function DiagnosticsPanel() {
  const { data: rejections } = useRejections(30);

  const reasonCounts: Record<string, number> = {};
  for (const r of rejections || []) {
    reasonCounts[r.reason] = (reasonCounts[r.reason] || 0) + 1;
  }
  const sortedReasons = Object.entries(reasonCounts).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
        <span>🚫</span> Trade Rejections
        <span className="text-xs text-slate-500 font-normal ml-auto">
          Last {rejections?.length || 0} entries
        </span>
      </h3>

      {/* Reason summary */}
      {sortedReasons.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {sortedReasons.map(([reason, count]) => (
            <span
              key={reason}
              className="px-2 py-0.5 rounded-full text-[10px] bg-red-500/10 text-red-300 border border-red-500/20"
            >
              {reason}: {count}
            </span>
          ))}
        </div>
      )}

      {/* Recent rejections */}
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {!rejections?.length ? (
          <p className="text-xs text-slate-500 italic">
            No rejections logged yet — the strategy hasn't rejected any trades.
          </p>
        ) : (
          rejections.map((r, i) => (
            <div
              key={`${r.timestamp}-${i}`}
              className="flex items-center gap-2 text-xs"
            >
              <span className="text-slate-500 font-mono w-16 shrink-0">
                {new Date(r.timestamp).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "UTC",
                })}{" "}
                <span className="text-[9px]">UTC</span>
              </span>
              <span
                className={`w-12 shrink-0 font-medium ${
                  r.side === "short" ? "text-red-400" : "text-emerald-400"
                }`}
              >
                {r.side?.toUpperCase() || "—"}
              </span>
              <span className="text-slate-400 truncate">{r.reason}</span>
              <span className="text-slate-600 ml-auto shrink-0">
                {r.regime}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

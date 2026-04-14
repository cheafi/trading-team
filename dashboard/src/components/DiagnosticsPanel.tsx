"use client";

import { useState } from "react";
import { useRejections, useDecisionJournal } from "@/lib/hooks";

export function DiagnosticsPanel() {
  const [tab, setTab] = useState<"journal" | "rejections">("journal");
  const [pairFilter, setPairFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<string>("");

  // Decision Journal v4 — unified accept+reject log
  const { data: journal } = useDecisionJournal({
    pair: pairFilter || undefined,
    decision: decisionFilter || undefined,
    limit: 200,
  });

  // Legacy rejections (still used for rejection-only breakdown)
  const { data: rejections } = useRejections(100);

  // ── Breakdowns from journal data ──
  const entries = journal?.entries || [];
  const reasonCounts: Record<string, number> = {};
  const pairCounts: Record<string, number> = {};
  const hourCounts: Record<number, number> = {};
  const regimeCounts: Record<string, number> = {};
  const sideCounts: Record<string, number> = {};

  // Use rejections for breakdowns (backward compat)
  for (const r of rejections || []) {
    reasonCounts[r.reason] = (reasonCounts[r.reason] || 0) + 1;
    const pair = r.pair || "unknown";
    pairCounts[pair] = (pairCounts[pair] || 0) + 1;
    const regime = r.regime != null ? String(r.regime) : "—";
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

  const pairs = ["ETH", "BTC", "SOL", "BNB", "XRP", "DOGE"];

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 space-y-4">
      {/* Header with tabs */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <span>📋</span> Decision Journal
          </h3>
          <div className="flex gap-1">
            <button
              onClick={() => setTab("journal")}
              className={`text-[10px] px-2 py-0.5 rounded ${
                tab === "journal"
                  ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                  : "text-slate-500 hover:text-slate-400"
              }`}
            >
              All Decisions
            </button>
            <button
              onClick={() => setTab("rejections")}
              className={`text-[10px] px-2 py-0.5 rounded ${
                tab === "rejections"
                  ? "bg-red-500/20 text-red-300 border border-red-500/30"
                  : "text-slate-500 hover:text-slate-400"
              }`}
            >
              Rejections
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Accept rate badge */}
          {journal && journal.total > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
              {(journal.acceptRate * 100).toFixed(1)}% accept rate
            </span>
          )}
          <span className="text-xs text-slate-500">
            {journal?.total || 0} total
          </span>
        </div>
      </div>

      {/* Summary cards */}
      {journal && journal.total > 0 && (
        <div className="grid grid-cols-4 gap-2">
          <div className="bg-slate-900/50 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-slate-200">{journal.total}</div>
            <div className="text-[9px] text-slate-500 uppercase">Total</div>
          </div>
          <div className="bg-slate-900/50 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-emerald-400">{journal.totalAccept}</div>
            <div className="text-[9px] text-slate-500 uppercase">Accepted</div>
          </div>
          <div className="bg-slate-900/50 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-red-400">{journal.totalReject}</div>
            <div className="text-[9px] text-slate-500 uppercase">Rejected</div>
          </div>
          <div className="bg-slate-900/50 rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-blue-400">
              {(journal.acceptRate * 100).toFixed(1)}%
            </div>
            <div className="text-[9px] text-slate-500 uppercase">Accept %</div>
          </div>
        </div>
      )}

      {tab === "journal" ? (
        <>
          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <select
              value={pairFilter}
              onChange={(e) => setPairFilter(e.target.value)}
              className="text-[10px] bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-300"
            >
              <option value="">All pairs</option>
              {pairs.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="text-[10px] bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-300"
            >
              <option value="">All decisions</option>
              <option value="accept">✅ Accepted</option>
              <option value="reject">🚫 Rejected</option>
            </select>
          </div>

          {/* Decision log */}
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {entries.length === 0 ? (
              <p className="text-xs text-slate-500 italic text-center py-4">
                No decisions logged yet — waiting for trade signals.
              </p>
            ) : (
              entries.slice(0, 50).map((d, i) => (
                <div
                  key={`${d.time}-${i}`}
                  className={`flex items-center gap-2 text-[11px] px-2 py-1 rounded ${
                    d.decision === "accept"
                      ? "bg-emerald-500/5 border-l-2 border-emerald-500/40"
                      : "bg-red-500/5 border-l-2 border-red-500/40"
                  }`}
                >
                  <span className={`w-4 shrink-0 text-center ${
                    d.decision === "accept" ? "text-emerald-400" : "text-red-400"
                  }`}>
                    {d.decision === "accept" ? "✓" : "✗"}
                  </span>
                  <span className="text-slate-600 font-mono w-12 shrink-0">
                    {d.time
                      ? new Date(d.time).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                          timeZone: "UTC",
                        })
                      : "—"}
                  </span>
                  <span className="text-slate-500 font-mono w-10 shrink-0">
                    {(d.pair || "").replace("/USDT:USDT", "").slice(0, 5)}
                  </span>
                  <span
                    className={`w-10 shrink-0 font-semibold ${
                      d.side === "short" ? "text-red-400" : "text-emerald-400"
                    }`}
                  >
                    {d.side?.toUpperCase() || "—"}
                  </span>
                  <span className="text-slate-400 truncate flex-1">
                    {d.reason}
                  </span>
                  {d.edge_score != null && (
                    <span className="text-[9px] text-purple-300 shrink-0 font-mono">
                      q={d.edge_score.toFixed(3)}
                    </span>
                  )}
                  {d.rate != null && (
                    <span className="text-[9px] text-slate-600 shrink-0 font-mono">
                      @{d.rate.toFixed(2)}
                    </span>
                  )}
                  <span className="text-slate-600 shrink-0">
                    R{d.regime != null ? d.regime : "?"}
                  </span>
                </div>
              ))
            )}
          </div>
        </>
      ) : (
        /* Rejections-only tab (original view) */
        <>
          {totalRejections === 0 ? (
            <p className="text-xs text-slate-500 italic text-center py-4">
              No rejections logged yet — the strategy hasn&apos;t rejected any trades.
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
                              <span className="text-slate-400 truncate">{reason}</span>
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
                              <span className="text-slate-500 ml-1 shrink-0">{count}</span>
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
                    const height = cnt > 0 ? Math.max(8, (cnt / maxHourCount) * 100) : 4;
                    const intensity =
                      cnt === 0
                        ? "bg-slate-700"
                        : cnt / maxHourCount > 0.7
                          ? "bg-red-500"
                          : cnt / maxHourCount > 0.3
                            ? "bg-amber-500"
                            : "bg-blue-500/60";
                    return (
                      <div key={h} className="flex-1 flex flex-col items-center gap-0.5">
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
                        {(r.pair || "").replace("/USDT:USDT", "").slice(0, 5)}
                      </span>
                      <span
                        className={`w-10 shrink-0 font-semibold ${
                          r.side === "short" ? "text-red-400" : "text-emerald-400"
                        }`}
                      >
                        {r.side?.toUpperCase() || "—"}
                      </span>
                      <span className="text-slate-400 truncate flex-1">{r.reason}</span>
                      <span className="text-slate-600 shrink-0">
                        R{r.regime != null ? r.regime : "?"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

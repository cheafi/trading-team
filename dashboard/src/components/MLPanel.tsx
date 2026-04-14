"use client";

import { useState, useRef, useEffect } from "react";
import {
  useMLState,
  useMLHistory,
  useMLJobs,
  useMLJobLogs,
  triggerMLTrain,
} from "@/lib/hooks";

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
  improving: { text: "↗ Improving", color: "text-emerald-400" },
  degrading: { text: "↘ Degrading", color: "text-red-400" },
  stable: { text: "→ Stable", color: "text-slate-400" },
};

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    running: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    finished: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    failed: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  const icons: Record<string, string> = {
    running: "⏳",
    finished: "✅",
    failed: "❌",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${styles[status] || styles.finished}`}
    >
      {icons[status] || "•"} {status}
    </span>
  );
}

function JobLogViewer({ jobId }: { jobId: string }) {
  const { data: logs } = useMLJobLogs(jobId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Redis LPUSH stores newest first — reverse for chronological order
  const ordered = [...(logs || [])].reverse();

  return (
    <div className="bg-[#0d1117] rounded-lg border border-slate-700/50 p-3 max-h-48 overflow-y-auto font-mono text-[10px] text-slate-300">
      {ordered.length === 0 ? (
        <p className="text-slate-500">No logs yet…</p>
      ) : (
        ordered.map((line, i) => (
          <div
            key={i}
            className={
              line.startsWith("[ERR]")
                ? "text-red-400"
                : line.startsWith("✅") || line.startsWith("🧠")
                  ? "text-emerald-400"
                  : line.startsWith("❌")
                    ? "text-red-400"
                    : ""
            }
          >
            {line}
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  );
}

export function MLPanel() {
  const { data: ml } = useMLState();
  const { data: history } = useMLHistory();
  const { data: jobs, mutate: refreshJobs } = useMLJobs(8);

  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [training, setTraining] = useState(false);
  const [trainMsg, setTrainMsg] = useState<string | null>(null);

  const regime = ml?.regime || "unknown";
  const regimeColor = REGIME_COLORS[regime] || "text-slate-400";
  const regimeEmoji = REGIME_EMOJI[regime] || "❓";
  const trend =
    TREND_DISPLAY[ml?.improvementTrend || "stable"] || TREND_DISPLAY.stable;

  const isRunning = jobs?.some((j) => j.status === "running");

  async function handleTrain() {
    setTraining(true);
    setTrainMsg(null);
    try {
      const result = await triggerMLTrain();
      if (result.jobId) {
        setTrainMsg(`Job started: ${result.jobId}`);
        setSelectedJob(result.jobId);
        refreshJobs();
      } else {
        setTrainMsg(result.error || "Unknown error");
      }
    } catch (err: unknown) {
      setTrainMsg(err instanceof Error ? err.message : "Request failed");
    } finally {
      setTraining(false);
    }
  }

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <span>🧠</span> ML Quality Gate
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">
            {ml?.lastTrained
              ? `Last trained: ${new Date(ml.lastTrained).toLocaleString("en-GB")}`
              : "Not yet trained"}
          </span>
          <button
            onClick={handleTrain}
            disabled={training || !!isRunning}
            className={`px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${
              training || isRunning
                ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-500 text-white cursor-pointer"
            }`}
          >
            {isRunning ? "⏳ Training..." : training ? "Starting..." : "🚀 Train"}
          </button>
        </div>
      </div>

      {trainMsg && (
        <div
          className={`text-[10px] mb-3 px-2 py-1 rounded ${
            trainMsg.startsWith("Job started")
              ? "bg-emerald-900/30 text-emerald-400"
              : "bg-red-900/30 text-red-400"
          }`}
        >
          {trainMsg}
        </div>
      )}

      {/* Active Regime */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">Current Regime</p>
          <p className={`text-sm font-bold ${regimeColor}`}>
            {regimeEmoji} {regime}
          </p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">Active Strategy</p>
          <p className="text-sm font-bold text-blue-400">
            {ml?.strategy || "—"}
          </p>
        </div>
        <div className="bg-[#111827] rounded-lg p-3 border border-slate-700/50">
          <p className="text-[10px] text-slate-500 mb-1">Model Trend</p>
          <p className={`text-sm font-bold ${trend.color}`}>{trend.text}</p>
        </div>
      </div>

      {/* Regime Params Table */}
      {ml?.params && (
        <div className="mb-4">
          <p className="text-[10px] text-slate-500 mb-2">
            Optimal Params per Regime
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

      {/* Training Jobs */}
      {jobs && jobs.length > 0 && (
        <div className="mb-4">
          <p className="text-[10px] text-slate-500 mb-2">
            Training Jobs
          </p>
          <div className="space-y-1">
            {jobs.slice(0, 5).map((job) => (
              <button
                key={job.id}
                onClick={() =>
                  setSelectedJob(selectedJob === job.id ? null : job.id)
                }
                className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-[10px] transition-colors ${
                  selectedJob === job.id
                    ? "bg-slate-700/60 border border-slate-600"
                    : "bg-[#111827] border border-transparent hover:border-slate-700/50"
                }`}
              >
                <div className="flex items-center gap-2">
                  <StatusBadge status={job.status} />
                  <span className="text-slate-400 font-mono">
                    {job.id.slice(0, 13)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-slate-500">
                  <span>
                    {new Date(job.startedAt).toLocaleTimeString("zh-TW")}
                  </span>
                  {job.finishedAt && (
                    <span>
                      (
                      {Math.round(
                        (new Date(job.finishedAt).getTime() -
                          new Date(job.startedAt).getTime()) /
                          1000
                      )}
                      s)
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Log Viewer */}
      {selectedJob && (
        <div className="mb-4">
          <p className="text-[10px] text-slate-500 mb-2">
            📋 Job Logs:{" "}
            <span className="font-mono">{selectedJob.slice(0, 13)}</span>
          </p>
          <JobLogViewer jobId={selectedJob} />
        </div>
      )}

      {/* Training History Sparkline */}
      {history && history.length > 0 && (
        <div>
          <p className="text-[10px] text-slate-500 mb-2">
            Training History ({history.length} runs)
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

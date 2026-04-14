"use client";

import { useFindings } from "@/lib/hooks";

const AGENT_EMOJI: Record<string, string> = {
  "quant-researcher": "🔬",
  backtester: "📊",
  "risk-manager": "🛡️",
  "signal-engineer": "📡",
  "market-analyst": "🌍",
  "security-auditor": "🔒",
};

export function FindingsPanel() {
  const { data: findings } = useFindings(30);

  if (!findings || findings.length === 0) {
    return (
      <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-6 text-center text-slate-500 text-sm">
        Waiting for agent reports...
      </div>
    );
  }

  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 max-h-[400px] overflow-y-auto">
      <div className="divide-y divide-slate-800/50">
        {findings.map((f, idx) => (
          <div
            key={`${f.timestamp}-${idx}`}
            className="px-4 py-3 hover:bg-slate-800/30 transition-colors"
          >
            <div className="flex items-start gap-3">
              <span className="text-lg mt-0.5">
                {AGENT_EMOJI[f.agent] || "🤖"}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-xs font-semibold text-slate-300">
                    {f.agent}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">
                    {f.type}
                  </span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  {f.summary}
                </p>
                <p className="text-[10px] text-slate-600 mt-1">
                  {new Date(f.timestamp).toLocaleString("zh-TW")}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

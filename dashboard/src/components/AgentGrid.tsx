"use client";

import { useAgents } from "@/lib/hooks";
import { clsx } from "clsx";

export function AgentGrid() {
  const { data: agents } = useAgents();

  if (!agents || agents.length === 0) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="bg-[#1a2332] rounded-xl border border-slate-800 p-4 animate-pulse h-32"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-3">
      {agents.map((agent) => (
        <div
          key={agent.id}
          className={clsx(
            "bg-[#1a2332] rounded-xl border p-4 card-hover",
            agent.status === "running"
              ? "border-blue-500/40 glow-blue"
              : agent.status === "error"
                ? "border-red-500/40 glow-red"
                : "border-slate-800"
          )}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-2xl">{agent.emoji}</span>
            <span
              className={clsx(
                "w-2 h-2 rounded-full",
                agent.status === "running"
                  ? "bg-blue-400 animate-pulse-dot"
                  : agent.status === "error"
                    ? "bg-red-400"
                    : "bg-emerald-400"
              )}
            />
          </div>
          <h3 className="text-sm font-semibold text-white truncate">
            {agent.name}
          </h3>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {agent.id}
          </p>
          <div className="mt-2 flex items-center justify-between">
            <span
              className={clsx(
                "text-[10px] px-1.5 py-0.5 rounded-full",
                agent.status === "running"
                  ? "bg-blue-500/20 text-blue-300"
                  : agent.status === "error"
                    ? "bg-red-500/20 text-red-300"
                    : "bg-emerald-500/20 text-emerald-300"
              )}
            >
              {agent.status === "running"
                ? "運行中"
                : agent.status === "error"
                  ? "錯誤"
                  : "待命"}
            </span>
            <span className="text-[10px] text-slate-500">
              {agent.findingsCount} 發現
            </span>
          </div>
          {agent.lastRun && (
            <p className="text-[9px] text-slate-600 mt-1.5 truncate">
              {new Date(agent.lastRun).toLocaleTimeString("zh-TW")}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

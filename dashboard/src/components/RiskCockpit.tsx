"use client";

import { useState } from "react";
import {
  useRiskCockpit,
  useModelRegistry,
  useKillSwitch,
  toggleKillSwitch,
} from "@/lib/hooks";
import { mutate } from "swr";

function Stat({
  label,
  value,
  color = "text-white",
  sub,
}: {
  label: string;
  value: string | number;
  color?: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-slate-500 uppercase tracking-wide">
        {label}
      </span>
      <span className={`text-lg font-mono font-semibold ${color}`}>
        {value}
      </span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}

export function RiskCockpit() {
  const { data: risk, isLoading } = useRiskCockpit();
  const { data: registry } = useModelRegistry();
  const { data: killSwitch } = useKillSwitch();
  const [toggling, setToggling] = useState(false);

  if (isLoading || !risk) {
    return (
      <div className="bg-slate-800 rounded-xl p-4 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-1/3 mb-3"></div>
        <div className="h-20 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const ddPct = (risk.max_drawdown * 100).toFixed(2);
  const ddColor =
    risk.max_drawdown > 0.15
      ? "text-red-400"
      : risk.max_drawdown > 0.1
        ? "text-amber-400"
        : "text-emerald-400";

  const driftStatus = risk.model_drift?.status || "unknown";
  const driftColor = risk.model_drift?.drifted
    ? "text-red-400"
    : "text-emerald-400";
  const driftIcon = risk.model_drift?.drifted ? "⚠️" : "✅";

  const activeVersion = registry?.active || risk.model_drift?.active_version;
  const activeEntry = registry?.versions?.find(
    (v) => v.version_id === activeVersion,
  );

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      {/* Exposure row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat
          label="Open Trades"
          value={risk.open_trades}
          color={risk.open_trades >= 4 ? "text-amber-400" : "text-white"}
        />
        <Stat
          label="Gross Exposure"
          value={`$${risk.gross_exposure.toFixed(2)}`}
        />
        <Stat
          label="Net Exposure"
          value={`$${(risk.net_exposure || 0).toFixed(2)}`}
          color={Math.abs(risk.net_exposure || 0) > 500 ? "text-amber-400" : "text-white"}
          sub={risk.net_exposure < 0 ? "net short" : risk.net_exposure > 0 ? "net long" : "flat"}
        />
        <Stat
          label="Worst-Case Loss"
          value={`$${risk.worst_case_loss.toFixed(2)}`}
          color="text-amber-400"
          sub="all SL hit"
        />
      </div>

      {/* DD Guard + Leverage row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat
          label="Max Drawdown"
          value={`${ddPct}%`}
          color={ddColor}
          sub={`$${(risk.max_drawdown_abs || 0).toFixed(2)}`}
        />
        <Stat
          label="Daily P&L"
          value={risk.dd_guard
            ? `${risk.dd_guard.daily_pnl >= 0 ? "+" : ""}$${risk.dd_guard.daily_pnl.toFixed(2)}`
            : "—"}
          color={
            risk.dd_guard?.daily_breached ? "text-red-400"
            : (risk.dd_guard?.daily_pnl || 0) < 0 ? "text-amber-400"
            : "text-emerald-400"
          }
          sub={risk.dd_guard
            ? `${risk.dd_guard.daily_trades} trades · limit ${(risk.dd_guard.daily_limit * 100).toFixed(0)}%`
            : ""}
        />
        <Stat
          label="Weekly P&L"
          value={risk.dd_guard
            ? `${risk.dd_guard.weekly_pnl >= 0 ? "+" : ""}$${risk.dd_guard.weekly_pnl.toFixed(2)}`
            : "—"}
          color={
            risk.dd_guard?.weekly_breached ? "text-red-400"
            : (risk.dd_guard?.weekly_pnl || 0) < 0 ? "text-amber-400"
            : "text-emerald-400"
          }
          sub={risk.dd_guard
            ? `${risk.dd_guard.weekly_trades} trades · limit ${(risk.dd_guard.weekly_limit * 100).toFixed(0)}%`
            : ""}
        />
        <Stat
          label="Leverage"
          value={risk.leverage
            ? risk.leverage.max > 0 ? `${risk.leverage.max}×` : "—"
            : "—"}
          color={risk.leverage?.max > 5 ? "text-amber-400" : "text-white"}
          sub={risk.leverage?.avg > 0 ? `avg ${risk.leverage.avg.toFixed(1)}×` : ""}
        />
      </div>

      {/* DD Guard breach warnings */}
      {(risk.dd_guard?.daily_breached || risk.dd_guard?.weekly_breached) && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          <span className="text-red-400 text-sm font-semibold">
            ⚠️ DD Guard Breached
          </span>
          <div className="text-red-300 text-xs mt-1">
            {risk.dd_guard?.daily_breached && <div>Daily loss limit breached ({(risk.dd_guard.daily_pnl_pct * 100).toFixed(2)}% &lt; {(risk.dd_guard.daily_limit * 100).toFixed(0)}%)</div>}
            {risk.dd_guard?.weekly_breached && <div>Weekly loss limit breached ({(risk.dd_guard.weekly_pnl_pct * 100).toFixed(2)}% &lt; {(risk.dd_guard.weekly_limit * 100).toFixed(0)}%)</div>}
          </div>
        </div>
      )}

      {/* Model + Drift row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat
          label="Model Drift"
          value={`${driftIcon} ${driftStatus}`}
          color={driftColor}
        />
        <Stat
          label="Active Model"
          value={activeVersion ? activeVersion.slice(0, 15) : "—"}
          sub={activeEntry?.params_hash || ""}
        />
        <Stat
          label="Max Concentration"
          value={`$${risk.max_concentration.toFixed(2)}`}
          sub="single pair"
        />
        <Stat
          label="Model Versions"
          value={registry?.versions?.length || 0}
          sub="tracked"
        />
      </div>

      {/* Pair exposure breakdown */}
      {risk.pair_exposure && Object.keys(risk.pair_exposure).length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide mb-1 block">
            Pair Exposure
          </span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(risk.pair_exposure)
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .map(([pair, amount]) => (
                <span
                  key={pair}
                  className="bg-slate-700 rounded px-2 py-1 text-xs font-mono"
                >
                  {pair.split("/")[0]}{" "}
                  <span className="text-amber-400">
                    ${(amount as number).toFixed(0)}
                  </span>
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Kill Switch */}
      <div className="border-t border-slate-700 pt-3">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-slate-500 uppercase tracking-wide">
              Kill Switch
            </span>
            <div className="flex items-center gap-2 mt-1">
              <span
                className={`inline-block w-3 h-3 rounded-full ${
                  killSwitch?.active
                    ? "bg-red-500 animate-pulse"
                    : "bg-emerald-500"
                }`}
              />
              <span
                className={`text-sm font-mono ${
                  killSwitch?.active ? "text-red-400" : "text-emerald-400"
                }`}
              >
                {killSwitch?.active ? "🛑 ACTIVE — all entries blocked" : "✅ Off — trading normal"}
              </span>
            </div>
            {killSwitch?.active && killSwitch.activated_at && (
              <span className="text-xs text-slate-500">
                Since {new Date(killSwitch.activated_at).toLocaleString()}
                {killSwitch.reason ? ` — ${killSwitch.reason}` : ""}
              </span>
            )}
          </div>
          <button
            disabled={toggling}
            onClick={async () => {
              setToggling(true);
              try {
                await toggleKillSwitch(
                  !killSwitch?.active,
                  killSwitch?.active ? undefined : "operator_dashboard",
                );
                mutate("/api/kill-switch");
              } finally {
                setToggling(false);
              }
            }}
            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
              killSwitch?.active
                ? "bg-emerald-700 hover:bg-emerald-600 text-white"
                : "bg-red-700 hover:bg-red-600 text-white"
            } ${toggling ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            {toggling
              ? "..."
              : killSwitch?.active
                ? "Deactivate"
                : "🛑 Activate Kill Switch"}
          </button>
        </div>
      </div>
    </div>
  );
}

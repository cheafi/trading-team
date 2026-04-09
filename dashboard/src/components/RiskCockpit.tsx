"use client";

import { useRiskCockpit, useModelRegistry } from "@/lib/hooks";

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
          label="Max Concentration"
          value={`$${risk.max_concentration.toFixed(2)}`}
          sub="single pair"
        />
        <Stat
          label="Worst-Case Loss"
          value={`$${risk.worst_case_loss.toFixed(2)}`}
          color="text-amber-400"
          sub="all SL hit"
        />
      </div>

      {/* Drawdown + Drift row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat
          label="Max Drawdown"
          value={`${ddPct}%`}
          color={ddColor}
          sub={`$${(risk.max_drawdown_abs || 0).toFixed(2)}`}
        />
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
    </div>
  );
}

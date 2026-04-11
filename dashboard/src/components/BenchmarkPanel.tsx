"use client";

import { useBenchmark } from "@/lib/hooks";

function Metric({
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

export function BenchmarkPanel() {
  const { data, isLoading } = useBenchmark();

  if (isLoading || !data) {
    return (
      <div className="bg-slate-800 rounded-xl p-4 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-1/3 mb-3"></div>
        <div className="h-20 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const retColor =
    data.strategy_return_pct > 0
      ? "text-emerald-400"
      : data.strategy_return_pct < 0
        ? "text-red-400"
        : "text-slate-400";

  const sharpeColor =
    data.sharpe > 1
      ? "text-emerald-400"
      : data.sharpe > 0
        ? "text-amber-400"
        : "text-red-400";

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">
        📊 Benchmark Centre
      </h3>

      {/* Core metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Metric
          label="Strategy Return"
          value={`${data.strategy_return_pct.toFixed(2)}%`}
          color={retColor}
          sub={`${data.trading_days}d`}
        />
        <Metric
          label="Sharpe"
          value={data.sharpe.toFixed(2)}
          color={sharpeColor}
        />
        <Metric
          label="Sortino"
          value={data.sortino.toFixed(2)}
          color={sharpeColor}
        />
        <Metric
          label="Calmar"
          value={data.calmar.toFixed(2)}
          color={data.calmar > 0 ? "text-emerald-400" : "text-red-400"}
        />
      </div>

      {/* Risk metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Metric
          label="Max Drawdown"
          value={`${data.max_drawdown_pct}%`}
          color="text-amber-400"
        />
        <Metric
          label="Profit Factor"
          value={data.profit_factor.toFixed(2)}
          color={data.profit_factor > 1 ? "text-emerald-400" : "text-red-400"}
        />
        <Metric
          label="Win Rate"
          value={`${(data.win_rate * 100).toFixed(1)}%`}
          color={data.win_rate > 0.5 ? "text-emerald-400" : "text-amber-400"}
        />
        <Metric
          label="Trades"
          value={data.closed_trades}
          sub={`of ${data.trade_count} total`}
        />
      </div>

      {/* Benchmark comparison */}
      {data.benchmarks && Object.keys(data.benchmarks).length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide mb-1 block">
            vs Benchmarks
          </span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.benchmarks).map(([key, bm]) => {
              const diff = data.strategy_return_pct - bm.return_pct;
              const diffColor =
                diff > 0
                  ? "text-emerald-400"
                  : diff < 0
                    ? "text-red-400"
                    : "text-slate-400";
              return (
                <div
                  key={key}
                  className="bg-slate-700 rounded px-3 py-2 text-xs font-mono"
                >
                  <div className="text-slate-400">{bm.label}</div>
                  <div className={diffColor}>
                    {diff > 0 ? "+" : ""}
                    {diff.toFixed(2)}% α
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Per-pair breakdown */}
      {data.pair_breakdown && Object.keys(data.pair_breakdown).length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide mb-1 block">
            Pair P&L
          </span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.pair_breakdown)
              .sort(
                ([, a], [, b]) =>
                  (b as { profit_pct: number }).profit_pct -
                  (a as { profit_pct: number }).profit_pct,
              )
              .map(([pair, info]) => {
                const pInfo = info as { profit_pct: number; trades: number };
                const pColor =
                  pInfo.profit_pct > 0
                    ? "text-emerald-400"
                    : pInfo.profit_pct < 0
                      ? "text-red-400"
                      : "text-slate-400";
                return (
                  <span
                    key={pair}
                    className="bg-slate-700 rounded px-2 py-1 text-xs font-mono"
                  >
                    {pair.split("/")[0]}{" "}
                    <span className={pColor}>
                      {pInfo.profit_pct.toFixed(2)}%
                    </span>{" "}
                    <span className="text-slate-500">({pInfo.trades}t)</span>
                  </span>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

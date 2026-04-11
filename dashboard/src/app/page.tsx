import { TeamHeader } from "@/components/TeamHeader";
import { AgentGrid } from "@/components/AgentGrid";
import { StrategyRanking } from "@/components/StrategyRanking";
import { FindingsPanel } from "@/components/FindingsPanel";
import { RiskGauge } from "@/components/RiskGauge";
import { PnLCard } from "@/components/PnLCard";
import { MLPanel } from "@/components/MLPanel";
import { TradesPanel } from "@/components/TradesPanel";
import { PairPerformance } from "@/components/PairPerformance";
import { EquityMini } from "@/components/EquityMini";
import { DiagnosticsPanel } from "@/components/DiagnosticsPanel";
import { RiskCockpit } from "@/components/RiskCockpit";
import { BenchmarkPanel } from "@/components/BenchmarkPanel";

export default function Home() {
  return (
    <main className="min-h-screen p-4 md:p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <TeamHeader />

      {/* Top row: P&L + Risk + Trade Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <PnLCard />
        <RiskGauge />
        <EquityMini />
      </div>

      {/* Middle row: Open Trades + Pair Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <TradesPanel />
        <PairPerformance />
      </div>

      {/* ML Adaptive Engine */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🧠</span> ML Adaptive Engine
        </h2>
        <MLPanel />
      </section>

      {/* Agent cards */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🤖</span> Team Agents
        </h2>
        <AgentGrid />
      </section>

      {/* Bottom row: Strategy Ranking + Findings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📊</span> Strategy Ranking
          </h2>
          <StrategyRanking />
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📋</span> Latest Findings
          </h2>
          <FindingsPanel />
        </section>
      </div>

      {/* Diagnostics: rejection journal */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🔍</span> Operator Diagnostics
        </h2>
        <DiagnosticsPanel />
      </section>

      {/* Risk Cockpit: exposure, drift, model versions, kill-switch */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🛡️</span> Risk Cockpit
        </h2>
        <RiskCockpit />
      </section>

      {/* Benchmark Centre: strategy vs benchmarks, risk-adjusted metrics */}
      <section className="mb-6">
        <BenchmarkPanel />
      </section>
    </main>
  );
}

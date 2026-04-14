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
import { BacktestPanel } from "@/components/BacktestPanel";
import { TradeHistory } from "@/components/TradeHistory";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ConnectionBanner } from "@/components/ConnectionBanner";

export default function Home() {
  return (
    <main className="min-h-screen p-4 md:p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <TeamHeader />

      {/* Global connection warning */}
      <ConnectionBanner />

      {/* Paper trading watermark */}
      <div className="mb-4 px-3 py-1.5 rounded-lg bg-amber-500/5 border border-amber-500/20 text-center">
        <span className="text-[10px] text-amber-400/80 font-medium tracking-wide">
          📋 PAPER TRADING — All figures are simulated. Not real money.
        </span>
      </div>

      {/* Top row: P&L + Risk + Trade Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <ErrorBoundary name="P&L">
          <PnLCard />
        </ErrorBoundary>
        <ErrorBoundary name="Risk Gauge">
          <RiskGauge />
        </ErrorBoundary>
        <ErrorBoundary name="Trade Stats">
          <EquityMini />
        </ErrorBoundary>
      </div>

      {/* Middle row: Open Trades + Pair Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <ErrorBoundary name="Open Trades">
          <TradesPanel />
        </ErrorBoundary>
        <ErrorBoundary name="Pair Performance">
          <PairPerformance />
        </ErrorBoundary>
      </div>

      {/* Trade History (closed trades) */}
      <section className="mb-6">
        <ErrorBoundary name="Trade History">
          <TradeHistory />
        </ErrorBoundary>
      </section>

      {/* Benchmark Centre: strategy vs benchmarks, risk-adjusted metrics */}
      <section className="mb-6">
        <ErrorBoundary name="Benchmark">
          <BenchmarkPanel />
        </ErrorBoundary>
      </section>

      {/* Backtest Lab: run backtests with custom time/TF/strategy */}
      <section className="mb-6">
        <ErrorBoundary name="Backtest Lab">
          <BacktestPanel />
        </ErrorBoundary>
      </section>

      {/* ML Quality Gate */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🧠</span> ML Quality Gate
        </h2>
        <ErrorBoundary name="ML Quality Gate">
          <MLPanel />
        </ErrorBoundary>
      </section>

      {/* Decision Journal: unified accept/reject log with search */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">📋</span> Decision Journal
        </h2>
        <ErrorBoundary name="Decision Journal">
          <DiagnosticsPanel />
        </ErrorBoundary>
      </section>

      {/* Risk Cockpit: exposure, drift, model versions, kill-switch */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🛡️</span> Risk Cockpit
        </h2>
        <ErrorBoundary name="Risk Cockpit">
          <RiskCockpit />
        </ErrorBoundary>
      </section>

      {/* Agent cards */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🤖</span> Team Agents
        </h2>
        <ErrorBoundary name="Team Agents">
          <AgentGrid />
        </ErrorBoundary>
      </section>

      {/* Bottom row: Strategy Ranking + Findings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📊</span> Strategy Ranking
          </h2>
          <ErrorBoundary name="Strategy Ranking">
            <StrategyRanking />
          </ErrorBoundary>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📋</span> Latest Findings
          </h2>
          <ErrorBoundary name="Latest Findings">
            <FindingsPanel />
          </ErrorBoundary>
        </section>
      </div>
    </main>
  );
}

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
          <span className="text-xl">🧠</span> ML 自適應引擎 Adaptive Engine
        </h2>
        <MLPanel />
      </section>

      {/* Agent cards */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-xl">🤖</span> 團隊成員 Team Agents
        </h2>
        <AgentGrid />
      </section>

      {/* Bottom row: Strategy Ranking + Findings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📊</span> 策略排名 Strategy Ranking
          </h2>
          <StrategyRanking />
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <span className="text-xl">📋</span> 最新發現 Latest Findings
          </h2>
          <FindingsPanel />
        </section>
      </div>
    </main>
  );
}

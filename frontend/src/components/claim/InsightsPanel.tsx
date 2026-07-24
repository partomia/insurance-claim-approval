import { RadialScoreGauges } from "./charts/RadialScoreGauges";
import { CoverageDonutChart } from "./charts/CoverageDonutChart";
import { ScoreComparisonBarChart } from "./charts/ScoreComparisonBarChart";
import { PayoutWaterfallChart } from "./charts/PayoutWaterfallChart";
import { PolicySummaryCard } from "./PolicySummaryCard";

interface PolicySummary {
  policy_type?: string;
  coverage_limit?: number;
  deductible?: number;
  co_pay_pct?: number;
}

interface Insights {
  coverage_utilization?: { claim_amount: number; limit: number; pct: number };
  score_gauges?: { confidence: number; fraud: number; evidence: number };
  payout_breakdown?: {
    gross: number;
    deductible: number;
    payable: number;
    co_pay_pct?: number;
    co_pay_amount?: number;
    depreciation_amount?: number;
    steps?: { name: string; value: number }[];
  };
  policy_sections?: { ref: string; category: string; summary: string }[];
  retrieved_primary_clause?: { ref: string; summary?: string } | null;
  escalation_flags?: string[];
  policy_context_summary?: string;
  policy_summary?: PolicySummary;
}

export function InsightsPanel({ insights }: { insights: Insights | null }) {
  if (!insights) {
    return <div className="text-sm text-muted-foreground p-2">Loading insights...</div>;
  }

  const util = insights.coverage_utilization;
  const gauges = insights.score_gauges;
  const payout = insights.payout_breakdown;
  const clauseMismatch = insights.escalation_flags?.includes("clause_mismatch") ?? false;

  return (
    <div className="space-y-4">
      <PolicySummaryCard
        policy={insights.policy_summary}
        policyContextSummary={insights.policy_context_summary}
        policySections={insights.policy_sections}
        retrievedPrimaryClause={insights.retrieved_primary_clause}
        clauseMismatch={clauseMismatch}
      />

      {gauges && (
        <div className="p-4 bg-card border rounded-lg shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Score Gauges
          </p>
          <RadialScoreGauges gauges={gauges} />
        </div>
      )}

      {util && (
        <div className="p-4 bg-card border rounded-lg shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Coverage Utilization
          </p>
          <CoverageDonutChart util={util} />
        </div>
      )}

      {gauges && (
        <div className="p-4 bg-card border rounded-lg shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Score Comparison
          </p>
          <ScoreComparisonBarChart gauges={gauges} />
        </div>
      )}

      {payout && payout.payable > 0 && (
        <div className="p-4 bg-card border rounded-lg shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Payout Breakdown
          </p>
          <PayoutWaterfallChart payout={payout} />
        </div>
      )}
    </div>
  );
}

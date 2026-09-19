import { RadialScoreGauges } from "./charts/RadialScoreGauges";
import { CoverageDonutChart } from "./charts/CoverageDonutChart";
import { ScoreComparisonBarChart } from "./charts/ScoreComparisonBarChart";
import { PayoutWaterfallChart } from "./charts/PayoutWaterfallChart";
import { PolicySummaryCard } from "./PolicySummaryCard";
import { RiskBandBadge } from "./RiskBandBadge";
import { Database, AlertTriangle } from "lucide-react";

interface PolicySummary {
  policy_type?: string;
  coverage_limit?: number;
  deductible?: number;
  co_pay_pct?: number;
}

interface PolicyRiskSignal {
  total_claims_count: number;
  claims_count_12m: number;
  total_claimed_amount: number;
  avg_claim_amount: number;
  amount_vs_segment_avg_pct?: number | null;
  linked_high_risk_garage: boolean;
  fraud_risk_score: number;
  claim_risk_band: string;
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
  policy_risk_signal?: PolicyRiskSignal | null;
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

      {insights.policy_risk_signal && (
        <div className="p-4 bg-card border rounded-lg shadow-sm space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <Database className="h-3.5 w-3.5" />
              Lakehouse Risk Signal
            </p>
            <RiskBandBadge band={insights.policy_risk_signal.claim_risk_band} />
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Fraud risk score</p>
              <p className="font-semibold">{insights.policy_risk_signal.fraud_risk_score.toFixed(1)} / 100</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Claims (12m / total)</p>
              <p className="font-semibold">
                {insights.policy_risk_signal.claims_count_12m} / {insights.policy_risk_signal.total_claims_count}
              </p>
            </div>
          </div>
          {insights.policy_risk_signal.linked_high_risk_garage && (
            <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
              <AlertTriangle className="h-3.5 w-3.5" />
              This policy has claims history at a garage flagged as high-risk
            </p>
          )}
          <p className="text-[11px] text-muted-foreground">
            Computed by the CDE claims-analytics pipeline over this policy's full claims history —
            independent of the AI fraud score above.
          </p>
        </div>
      )}

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

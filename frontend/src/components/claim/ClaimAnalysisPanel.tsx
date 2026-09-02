import { useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileText,
  Shield,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { OPEN_ASSISTANT_EVENT } from "@/components/assistant/UniversalAssistant";
import { formatINR } from "@/lib/currency";

export interface AIAnalysis {
  approval_probability?: number;
  coverage_estimate?: number;
  expected_settlement?: number;
  confidence?: number;
  confidence_score?: number;
  potential_problems?: string[];
  recommendations?: string[];
  missing_documents?: string[];
  policy_clause_matches?: { section_ref: string; summary?: string; match_score?: number }[];
  fraud_signals?: { signal: string; severity?: string; score?: number }[];
  next_best_action?: string;
  ai_explanation?: string;
  reasoning?: string;
}

function pct(value?: number): string {
  if (value == null) return "—";
  const n = value <= 1 ? value * 100 : value;
  return `${Math.round(n)}%`;
}

function MetricCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-muted/40 p-4">
      <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-bold tracking-tight ${valueClass ?? ""}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs font-medium text-muted-foreground">{sub}</p>}
    </div>
  );
}

export function ClaimAnalysisPanel({
  analysis,
  claimId,
  onContinue,
  showHeader = true,
  showNextAction = true,
}: {
  analysis: AIAnalysis | null;
  claimId?: string;
  status?: string;
  onContinue?: (action: string) => boolean | void;
  showHeader?: boolean;
  showNextAction?: boolean;
}) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleContinue = () => {
    const action = analysis?.next_best_action;
    if (!action) return;
    if (onContinue?.(action)) return;
    window.dispatchEvent(new CustomEvent(OPEN_ASSISTANT_EVENT, { detail: { prompt: action } }));
    navigate({ pathname: location.pathname, search: location.search, hash: "assistant" });
  };

  if (!analysis) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center text-muted-foreground">
        <Sparkles className="mx-auto mb-3 h-10 w-10 opacity-40" />
        <p className="font-medium">AI analysis will appear here once processing completes.</p>
      </div>
    );
  }

  const approval = analysis.approval_probability ?? 0;
  const approvalColor =
    approval >= 0.85
      ? "text-success"
      : approval >= 0.6
        ? "text-warning"
        : "text-destructive";

  return (
    <div className="space-y-5">
      {showHeader && (
        <div>
          <h2 className="text-xl font-semibold">
            {claimId ? `Analysis for ${claimId}` : "Claim analysis"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Guidance before insurer submission — not a final decision.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="Approval" value={pct(approval)} valueClass={approvalColor} sub="Likely approval" />
        <MetricCard label="Coverage" value={formatINR(analysis.coverage_estimate ?? 0)} sub="Eligible amount" />
        <MetricCard label="Settlement" value={formatINR(analysis.expected_settlement ?? 0)} sub="After deductions" />
        <MetricCard
          label="Confidence"
          value={pct(analysis.confidence ?? analysis.confidence_score)}
          sub="Model certainty"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4 text-warning" />
            Potential problems
          </div>
          {(analysis.potential_problems?.length ?? 0) > 0 ? (
            <ul className="space-y-2">
              {analysis.potential_problems!.map((p) => (
                <li key={p} className="flex gap-2 text-sm">
                  <span className="text-warning">•</span>
                  {p}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No significant issues detected.</p>
          )}
        </div>

        <div className="rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <TrendingUp className="h-4 w-4 text-success" />
            Recommendations
          </div>
          {(analysis.recommendations?.length ?? 0) > 0 ? (
            <ul className="space-y-2">
              {analysis.recommendations!.map((r) => (
                <li key={r} className="flex gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                  {r}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No recommendations at this time.</p>
          )}
        </div>
      </div>

      {(analysis.policy_clause_matches?.length ?? 0) > 0 && (
        <div className="rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Shield className="h-4 w-4 text-muted-foreground" />
            Policy clauses
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {analysis.policy_clause_matches!.map((c) => (
              <div
                key={c.section_ref}
                className="rounded-md border bg-muted/40 px-3 py-2.5"
              >
                <p className="text-sm font-semibold">{c.section_ref}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {c.summary || "Relevant coverage clause"}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {(analysis.ai_explanation || analysis.reasoning) && (
        <div className="rounded-lg border bg-muted/40 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <FileText className="h-4 w-4" />
            AI explanation
          </div>
          <p className="text-sm leading-relaxed">
            {analysis.ai_explanation || analysis.reasoning}
          </p>
        </div>
      )}

      {showNextAction && analysis.next_best_action && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
              Suggested next step
            </p>
            <p className="mt-0.5 font-medium">{analysis.next_best_action}</p>
          </div>
          <Button type="button" size="sm" onClick={handleContinue}>
            Continue <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
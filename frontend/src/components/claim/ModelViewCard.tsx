import { BrainCircuit, CheckCircle2, HelpCircle, XCircle } from "lucide-react";

export interface ModelFactor {
  feature: string;
  direction: "raises" | "lowers" | string;
  effect: number;
  value: number | string | null;
  typical: number | string | null;
}

export interface ModelGuardrail {
  guardrail: string;
  passed: boolean;
  reason?: string | null;
}

export interface ModelView {
  mode?: string;
  scored_at?: string;
  rules_decision?: string | null;
  error?: string;
  p_approve?: number | null;
  p_fraud?: number | null;
  approval_band?: string | null;
  fraud_band?: string | null;
  band_reason?: string | null;
  agrees_with_rules?: boolean | null;
  top_factors?: { approval?: ModelFactor[]; fraud?: ModelFactor[] };
  guardrails?: ModelGuardrail[];
  model?: Record<string, { version?: string; registry_name?: string; registry_version?: number; test_auroc?: number }>;
  policy_in_lakehouse?: boolean;
}

const BAND_LABEL: Record<string, string> = {
  LIKELY_APPROVE: "Likely approve",
  NEUTRAL: "Neutral",
  REVIEW: "Review",
  UNCERTAIN: "Uncertain",
  ABSTAIN: "Abstained",
  FRAUD_REVIEW: "Fraud review",
  CLEAR: "Clear",
};

const pct = (p?: number | null) => (p == null ? "—" : `${Math.round(p * 100)}%`);
const label = (f: string) => f.replace(/_/g, " ");

function Agreement({ agrees }: { agrees?: boolean | null }) {
  if (agrees === true)
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-success">
        <CheckCircle2 className="h-3.5 w-3.5" /> Agrees with the rules
      </span>
    );
  if (agrees === false)
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-warning">
        <XCircle className="h-3.5 w-3.5" /> Disagrees with the rules
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <HelpCircle className="h-3.5 w-3.5" /> No comparison
    </span>
  );
}

export function ModelViewCard({ view }: { view: ModelView }) {
  const approval = view.model?.approval;
  const failed = (view.guardrails ?? []).filter((g) => !g.passed);

  return (
    <div className="p-4 bg-card border rounded-lg shadow-sm space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <BrainCircuit className="h-3.5 w-3.5" />
          Model view
        </p>
        {!view.error && <Agreement agrees={view.agrees_with_rules} />}
      </div>

      {view.error ? (
        <p className="text-xs text-muted-foreground">Model not available for this claim ({view.error}).</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Approval</p>
              <p className="font-semibold">
                {pct(view.p_approve)}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {BAND_LABEL[view.approval_band ?? ""] ?? view.approval_band}
                </span>
              </p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Fraud review</p>
              <p className="font-semibold">
                {pct(view.p_fraud)}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {BAND_LABEL[view.fraud_band ?? ""] ?? view.fraud_band}
                </span>
              </p>
            </div>
          </div>

          {(view.top_factors?.approval ?? []).length > 0 && (
            <ul className="space-y-1">
              {view.top_factors!.approval!.slice(0, 4).map((f) => (
                <li key={f.feature} className="flex items-center justify-between gap-2 text-xs">
                  <span>
                    {label(f.feature)} <span className="text-muted-foreground">{String(f.value)} (typical {String(f.typical)})</span>
                  </span>
                  <span className={f.direction === "raises" ? "text-success" : "text-warning"}>{f.direction} approval</span>
                </li>
              ))}
            </ul>
          )}

          {failed.length > 0 && (
            <p className="text-xs text-warning">
              Guardrail: {failed.map((g) => g.reason || label(g.guardrail)).join("; ")}
            </p>
          )}
        </>
      )}

      <p className="text-[11px] text-muted-foreground">
        Shadow mode: a second opinion for the reviewer, never shown to the customer and never changes the decision.
        {approval?.version ? ` Model ${approval.version}` : ""}
        {approval?.test_auroc ? ` (test AUROC ${approval.test_auroc.toFixed(2)})` : ""}.
      </p>
    </div>
  );
}

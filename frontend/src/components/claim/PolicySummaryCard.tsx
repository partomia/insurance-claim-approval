import { Shield, IndianRupee, FileText, Percent, AlertTriangle } from "lucide-react";
import { formatINR } from "@/lib/currency";

interface PolicySummary {
  policy_type?: string;
  coverage_limit?: number;
  deductible?: number;
  co_pay_pct?: number;
}

interface PolicySection {
  ref: string;
  category?: string;
  summary?: string;
}

interface RetrievedClause {
  ref: string;
  summary?: string;
}

export function PolicySummaryCard({
  policy,
  policyContextSummary,
  policySections,
  retrievedPrimaryClause,
  clauseMismatch,
}: {
  policy?: PolicySummary | null;
  policyContextSummary?: string;
  policySections?: PolicySection[];
  retrievedPrimaryClause?: RetrievedClause | null;
  clauseMismatch?: boolean;
}) {
  const scheduleClause = policySections?.[0];
  const summarySnippet = policyContextSummary?.slice(0, 120);
  const displayClause = retrievedPrimaryClause || scheduleClause;

  return (
    <div className="p-4 bg-muted/30 border rounded-lg space-y-3">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-secondary" />
        <h4 className="font-semibold text-sm">Motor Policy Overview</h4>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {policy?.policy_type && (
          <div className="flex items-start gap-2">
            <Shield className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-[10px] uppercase text-muted-foreground tracking-wide">Type</p>
              <p className="text-sm font-medium">{policy.policy_type}</p>
            </div>
          </div>
        )}
        {policy?.coverage_limit != null && (
          <div className="flex items-start gap-2">
            <IndianRupee className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-[10px] uppercase text-muted-foreground tracking-wide">IDV / sum insured</p>
              <p className="text-sm font-medium">{formatINR(policy.coverage_limit)}</p>
            </div>
          </div>
        )}
        {policy?.deductible != null && (
          <div className="flex items-start gap-2">
            <IndianRupee className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-[10px] uppercase text-muted-foreground tracking-wide">Compulsory excess</p>
              <p className="text-sm font-medium">{formatINR(policy.deductible)}</p>
            </div>
          </div>
        )}
        {policy?.co_pay_pct != null && policy.co_pay_pct > 0 && (
          <div className="flex items-start gap-2">
            <Percent className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-[10px] uppercase text-muted-foreground tracking-wide">Co-pay</p>
              <p className="text-sm font-medium">{policy.co_pay_pct}%</p>
            </div>
          </div>
        )}
      </div>

      {(displayClause || summarySnippet) && (
        <div className={`flex items-start gap-2 pt-2 border-t ${clauseMismatch ? "text-warning" : ""}`}>
          {clauseMismatch ? (
            <AlertTriangle className="w-3.5 h-3.5 text-warning mt-0.5 shrink-0" />
          ) : (
            <FileText className="w-3.5 h-3.5 text-primary mt-0.5 shrink-0" />
          )}
          <div>
            <p className="text-[10px] uppercase text-muted-foreground tracking-wide">
              {retrievedPrimaryClause ? "Decision Clause (RAG)" : "Key Clause"}
            </p>
            {displayClause ? (
              <p className="text-xs leading-relaxed">
                <span className={`font-semibold ${clauseMismatch ? "text-warning" : "text-primary"}`}>
                  {displayClause.ref}
                </span>
                {displayClause.summary ? ` — ${displayClause.summary.slice(0, 80)}` : ""}
              </p>
            ) : (
              <p className="text-xs leading-relaxed text-muted-foreground">{summarySnippet}...</p>
            )}
            {clauseMismatch && scheduleClause && retrievedPrimaryClause && (
              <p className="text-xs text-warning mt-1">
                Schedule lists {scheduleClause.ref}; decision used {retrievedPrimaryClause.ref}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
import {
  AlertTriangle,
  ChevronRight,
  DollarSign,
  FileText,
  Shield,
} from "lucide-react";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { claimStatusLabel, riskLevelLabel } from "@/lib/claimStatusLabels";
import { formatEscalationList } from "@/lib/escalationLabels";

export interface ClaimHistoryCardData {
  id: number;
  claim_id: string;
  status: string;
  claim_amount: number;
  updated_at: string;
  assigned_agent?: string | null;
  escalation_flags?: string[];
  escalation_messages?: string[];
  document_count?: number;
  has_document_issues?: boolean;
  submission?: {
    policy_type?: string | null;
    policy_number?: string | null;
    location?: string;
  } | null;
  decision?: {
    fraud_score?: number;
    approval_probability?: number | null;
  } | null;
}

function formatUpdatedAt(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function ClaimHistoryCard({ claim }: { claim: ClaimHistoryCardData }) {
  const attentionItems = formatEscalationList(claim.escalation_messages, claim.escalation_flags);
  const needsAttention =
    attentionItems.length > 0 ||
    claim.has_document_issues ||
    claim.status === "REQUEST_MORE_INFO";

  const approvalPct =
    claim.decision?.approval_probability != null
      ? Math.round(claim.decision.approval_probability * 100)
      : null;

  const subtitleParts = [
    claim.submission?.policy_type,
    claim.submission?.policy_number,
    claim.submission?.location,
    `Updated ${formatUpdatedAt(claim.updated_at)}`,
  ].filter(Boolean);

  return (
    <article
      className={`group relative overflow-hidden rounded-xl border bg-card shadow-sm transition-all hover:shadow-md hover:border-primary/40 ${
        needsAttention ? "ring-warning-border" : ""
      }`}
    >
      {needsAttention && (
        <div className="absolute inset-y-0 left-0 w-1 bg-warning" aria-hidden />
      )}

      <div className="p-5 sm:p-6 space-y-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold tracking-tight">{claim.claim_id}</h2>
              {approvalPct != null && (
                <span className="inline-flex items-center rounded-full border border-success-border bg-success-subtle px-2.5 py-0.5 text-xs font-semibold text-success">
                  {approvalPct}% likely approved
                </span>
              )}
            </div>
            {subtitleParts.length > 0 && (
              <p className="text-sm text-muted-foreground">{subtitleParts.join(" · ")}</p>
            )}
          </div>

          <ClaimStatusBadge
            status={claim.status}
            assignedAgent={claim.assigned_agent}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-lg border bg-muted/30 px-4 py-3">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <DollarSign className="h-4 w-4" />
              <span className="text-xs font-medium uppercase tracking-wide">Claim amount</span>
            </div>
            <p className="text-xl font-semibold">${claim.claim_amount.toLocaleString()}</p>
          </div>

          <div className="rounded-lg border bg-muted/30 px-4 py-3">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <FileText className="h-4 w-4" />
              <span className="text-xs font-medium uppercase tracking-wide">Documents</span>
            </div>
            <p className="text-xl font-semibold">{claim.document_count ?? 0}</p>
            {claim.has_document_issues && (
              <p className="text-xs text-warning mt-1 inline-flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                Some need a closer look
              </p>
            )}
          </div>

          <div className="rounded-lg border bg-muted/30 px-4 py-3">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Shield className="h-4 w-4" />
              <span className="text-xs font-medium uppercase tracking-wide">Risk level</span>
            </div>
            {claim.decision?.fraud_score != null ? (
              <>
                <p className="text-xl font-semibold">
                  {riskLevelLabel(claim.decision.fraud_score)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {(claim.decision.fraud_score * 100).toFixed(0)}% automated check
                </p>
              </>
            ) : (
              <p className="text-xl font-semibold text-muted-foreground">—</p>
            )}
          </div>
        </div>

        {needsAttention && (
          <div className="rounded-lg border border-warning-border bg-warning-subtle px-4 py-3">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-sm font-medium">Needs your attention</p>
                {attentionItems.length > 0 ? (
                  <ul className="text-sm space-y-0.5">
                    {attentionItems.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : claim.status === "REQUEST_MORE_INFO" ? (
                  <p className="text-sm">We need more information or documents from you.</p>
                ) : (
                  <p className="text-sm">One or more documents may need to be updated.</p>
                )}
              </div>
              <ChevronRight className="hidden h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 sm:block" />
            </div>
          </div>
        )}

        {!needsAttention && (
          <div className="flex items-center justify-end text-sm text-muted-foreground">
            <span className="group-hover:text-primary transition-colors inline-flex items-center gap-1">
              View claim
              <ChevronRight className="h-4 w-4 group-hover:translate-x-0.5 transition-transform" />
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

export function claimNeedsAttention(claim: ClaimHistoryCardData): boolean {
  const attentionItems = formatEscalationList(claim.escalation_messages, claim.escalation_flags);
  return (
    attentionItems.length > 0 ||
    !!claim.has_document_issues ||
    claim.status === "REQUEST_MORE_INFO"
  );
}

export { claimStatusLabel };

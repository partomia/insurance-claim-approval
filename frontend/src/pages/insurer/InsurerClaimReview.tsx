import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { DetailHeader } from "@/components/ui/detail-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ClaimAnalysisPanel, type AIAnalysis } from "@/components/claim/ClaimAnalysisPanel";
import { ClaimSubmissionSummary, type ClaimDocumentItem, type ClaimSubmission } from "@/components/claim/ClaimSubmissionSummary";
import { AlertTriangle, ExternalLink, FileWarning } from "lucide-react";
import { InsightsPanel } from "@/components/claim/InsightsPanel";
import { ExpertPolicyRequirements } from "@/components/agent/ExpertPolicyRequirements";
import { insurerApiFetch, insurerApiJson } from "@/lib/insurerApi";
import { openInsurerClaimDocument } from "@/lib/insurerDocuments";
import { formatApiError, useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";

interface ClaimStatus {
  claim_id: string;
  id: number;
  status: string;
  claim_amount: number;
  assigned_agent?: string | null;
  expert_review?: {
    reviewer_notes?: string | null;
    summary?: string | null;
  } | null;
  escalation_flags?: string[];
  escalation_messages?: string[];
  evidence_issues?: Array<{
    field: string;
    document_id: number;
    filename: string;
    reason: string;
    issue_code: string;
    acknowledged?: boolean;
  }>;
  decision?: AIAnalysis & {
    expected_settlement?: number;
    payable_amount?: number;
  };
  submission?: ClaimSubmission;
  documents?: ClaimDocumentItem[];
}

export function InsurerClaimReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { success, error } = useToast();
  const [claim, setClaim] = useState<ClaimStatus | null>(null);
  const [insights, setInsights] = useState<Record<string, unknown> | null>(null);
  const [notes, setNotes] = useState("");
  const [payableAmount, setPayableAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      insurerApiJson<ClaimStatus>(`/api/insurer/claims/${id}`),
      insurerApiJson<Record<string, unknown>>(`/api/insurer/claims/${id}/insights`).catch(() => null),
    ])
      .then(([claimData, insightsData]) => {
        setClaim(claimData);
        setInsights(insightsData);
        const defaultPayable =
          claimData.decision?.expected_settlement ??
          claimData.decision?.payable_amount ??
          claimData.claim_amount;
        setPayableAmount(String(defaultPayable ?? ""));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setLoadError("Claim not found.");
        else setLoadError("Could not load claim.");
      });
  }, [id]);

  const submitDecision = async (action: "APPROVED" | "REJECTED") => {
    if (!id) return;
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = { action, notes: notes.trim() || undefined };
      if (action === "APPROVED") {
        const amount = parseFloat(payableAmount);
        if (Number.isNaN(amount) || amount < 0) {
          error("Enter a valid payable amount.");
          setSubmitting(false);
          return;
        }
        body.payable_amount = amount;
      }
      const res = await insurerApiFetch(
        `/api/insurer/claims/${id}/decision`,
        { method: "POST", body: JSON.stringify(body) },
        { json: true }
      );
      if (res.ok) {
        success(action === "APPROVED" ? "Claim approved." : "Claim rejected.");
        navigate("/insurer/claims");
      } else {
        error(formatApiError((await res.json()).detail));
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <p className="font-medium">{loadError}</p>
          <Button variant="outline" onClick={() => navigate("/insurer/claims")}>
            Back to claims
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!claim) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36" />
        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  const canDecide = claim.status === "SUBMITTED_TO_INSURER";
  const showDocIssues = (claim.evidence_issues?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <DetailHeader
        back={{ to: "/insurer/claims", label: "All claims" }}
        eyebrow="Insurer claim review"
        title={claim.claim_id}
        subtitle="Review submission, expert work, and AI analysis before your final decision."
        status={<ClaimStatusBadge status={claim.status} assignedAgent={claim.assigned_agent} />}
        actions={
          <Link to={`/insurer/claims/${id}/audit`}>
            <Button variant="outline" size="sm">Audit report</Button>
          </Link>
        }
        meta={
          claim.assigned_agent
            ? [{ label: "Claim expert", value: claim.assigned_agent }]
            : undefined
        }
      />

      {claim.submission && id && (
        <ClaimSubmissionSummary
          claimId={id}
          submission={claim.submission}
          documents={claim.documents}
          claimAmount={claim.claim_amount}
          openDocument={(doc) => openInsurerClaimDocument(id, doc.id)}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        <div className="space-y-6 min-w-0">
          <ClaimAnalysisPanel analysis={claim.decision ?? null} claimId={claim.claim_id} status={claim.status} />

          {id && <ExpertPolicyRequirements claimId={Number(id)} portal="insurer" />}

          {(claim.expert_review?.summary || claim.expert_review?.reviewer_notes) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Expert notes</CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-2">
                {claim.expert_review.summary && <p>{claim.expert_review.summary}</p>}
                {claim.expert_review.reviewer_notes && (
                  <p className="text-muted-foreground">{claim.expert_review.reviewer_notes}</p>
                )}
              </CardContent>
            </Card>
          )}

          {showDocIssues && id && (
            <Card className="shadow-sm ring-warning-border bg-warning-subtle">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <FileWarning className="w-5 h-5 text-warning" />
                  <CardTitle className="text-base">Documents flagged during review</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {(claim.evidence_issues ?? [])
                  .filter((issue) => !issue.acknowledged)
                  .map((issue) => (
                    <div key={`${issue.document_id}-${issue.issue_code}`} className="rounded-lg border bg-background p-4 space-y-2">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 text-warning mt-0.5 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-sm">{issue.field}</p>
                          <p className="text-xs text-muted-foreground">{issue.filename}</p>
                          <p className="text-sm mt-1">{issue.reason}</p>
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => openInsurerClaimDocument(id, issue.document_id)}
                      >
                        <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                        View document
                      </Button>
                    </div>
                  ))}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <InsightsPanel insights={insights} />

          {canDecide ? (
            <Card className="ring-secondary/30">
              <CardHeader>
                <CardTitle className="text-base">Final decision</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="payable">
                    Payable amount (if approved)
                  </label>
                  <Input
                    id="payable"
                    type="number"
                    min={0}
                    step="0.01"
                    value={payableAmount}
                    onChange={(e) => setPayableAmount(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="notes">
                    Decision notes
                  </label>
                  <Textarea
                    id="notes"
                    placeholder="Reason for approval or rejection (visible in audit trail)"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />
                </div>
                <Button
                  className="w-full bg-success text-success-foreground hover:bg-success/90"
                  disabled={submitting}
                  onClick={() => submitDecision("APPROVED")}
                >
                  Approve claim
                </Button>
                <Button
                  variant="destructive"
                  className="w-full"
                  disabled={submitting}
                  onClick={() => submitDecision("REJECTED")}
                >
                  Reject claim
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-6 text-sm text-muted-foreground">
                This claim has already been decided. Status: {claim.status.replace(/_/g, " ").toLowerCase()}.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

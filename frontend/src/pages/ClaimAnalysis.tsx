import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, ExternalLink, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DetailHeader } from "@/components/ui/detail-header";
import { SectionHeading } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimAnalysisPanel, type AIAnalysis } from "@/components/claim/ClaimAnalysisPanel";
import { ClaimSubmissionSummary, type ClaimDocumentItem, type ClaimSubmission } from "@/components/claim/ClaimSubmissionSummary";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ExpertRequestedDocumentsCard } from "@/components/claim/ExpertRequestedDocumentsCard";
import { ExpertReviewCard, type ExpertReview } from "@/components/claim/ExpertReviewCard";
import { AssignPolicyAgentModal } from "@/components/claim/AssignPolicyAgentModal";
import { apiJson } from "@/lib/api";
import { formatINR } from "@/lib/currency";

interface Decision extends AIAnalysis {
  claim_id: string;
  status: string;
  human_review_required?: boolean;
}

interface ClaimStatus {
  claim_id: string;
  id: number;
  status: string;
  claim_amount: number;
  assigned_agent?: string | null;
  assigned_at?: string | null;
  expert_review?: ExpertReview | null;
  decision?: Decision;
  submission?: ClaimSubmission;
  documents?: ClaimDocumentItem[];
}

export function ClaimAnalysis() {
  const { id } = useParams();
  const [claim, setClaim] = useState<ClaimStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    apiJson<ClaimStatus>(`/api/claims/${id}/status`)
      .then((data) => {
        setClaim(data);
        setLoadError(null);
      })
      .catch((err) => {
        setLoadError(err instanceof Error ? err.message : "Could not load analysis.");
      });
  }, [id]);

  if (loadError) {
    return (
      <Card>
        <CardContent className="py-16 text-center space-y-3">
          <p className="text-lg font-medium">We couldn't load this claim.</p>
          <p className="text-sm text-muted-foreground">{loadError}</p>
          <Link to="/history">
            <Button variant="outline">Back to claims</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  if (!claim) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36" />
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <Skeleton className="h-96" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  const analysis: AIAnalysis = claim.decision ?? {};
  const needsExpert = claim.status === "PENDING_REVIEW" && !claim.assigned_agent;
  const approvalPct = Math.round((analysis.approval_probability ?? 0) * 100);

  return (
    <div className="space-y-6 pb-10">
      <DetailHeader
        back={{ to: "/history", label: "All claims" }}
        eyebrow="AI claim analysis"
        title={claim.claim_id}
        subtitle={`Motor claim amount ${formatINR(claim.claim_amount)}`}
        status={
          <ClaimStatusBadge
            status={claim.status}
            assignedAgent={claim.assigned_agent}
            showExpert={!claim.expert_review}
          />
        }
        actions={
          <>
            {id && (
              <Link to={`/track/${id}`}>
                <Button variant="outline" size="sm">
                  Track claim <ExternalLink className="ml-1 h-3.5 w-3.5" />
                </Button>
              </Link>
            )}
            <Link to="/history">
              <Button variant="ghost" size="sm">
                Claim history
              </Button>
            </Link>
          </>
        }
        meta={
          approvalPct > 0
            ? [
                {
                  label: "AI approval probability",
                  value: `${approvalPct}%`,
                  tone: approvalPct >= 70 ? "success" : approvalPct >= 40 ? "warning" : "danger",
                },
              ]
            : undefined
        }
      />

      <div className="grid grid-cols-1 gap-6 items-start lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-6">
          <section className="rounded-xl border bg-card p-5 sm:p-6 shadow-sm">
            <SectionHeading
              icon={<Sparkles className="h-5 w-5 text-primary" />}
              title="AI motor claim analysis"
              className="mb-4"
            />
            <ClaimAnalysisPanel
              analysis={analysis}
              claimId={claim.claim_id}
              showHeader={false}
              showNextAction={!claim.expert_review || claim.expert_review.action !== "NEEDS_IMPROVEMENT"}
              onContinue={(action) => {
                if (action.toLowerCase().includes("expert")) {
                  setAssignOpen(true);
                  return true;
                }
                return false;
              }}
            />
          </section>

          {claim.submission && id && (
            <section className="space-y-3">
              <SectionHeading title="Your submission" />
              <ClaimSubmissionSummary
                claimId={id}
                submission={claim.submission}
                documents={claim.documents}
                claimAmount={claim.claim_amount}
              />
            </section>
          )}
        </div>

        <aside className="space-y-3">
          {claim.expert_review ? (
            <ExpertReviewCard review={claim.expert_review} assignedAt={claim.assigned_at} variant="sidebar" />
          ) : needsExpert ? (
            <div className="space-y-3 rounded-xl border border-dashed border-secondary/40 bg-secondary/5 p-5">
              <p className="text-sm font-semibold">No expert assigned yet</p>
              <p className="text-sm text-muted-foreground">
                Connect with a Claim Expert for help preparing a stronger submission.
              </p>
              <Button className="w-full" onClick={() => setAssignOpen(true)}>
                Get expert help <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          ) : null}

          {claim.expert_review?.requested_documents &&
            claim.expert_review.requested_documents.length > 0 &&
            id && (
              <ExpertRequestedDocumentsCard
                claimId={id}
                requestedDocuments={claim.expert_review.requested_documents}
                onUploaded={() => apiJson<ClaimStatus>(`/api/claims/${id}/status`).then(setClaim)}
              />
            )}

          {claim.expert_review?.action === "NEEDS_IMPROVEMENT" && id && (
            <Link to={`/track/${id}`} className="block">
              <Button className="w-full">
                Upload documents <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          )}
        </aside>
      </div>

      <AssignPolicyAgentModal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        claimId={String(claim.id)}
        onAssigned={() => apiJson<ClaimStatus>(`/api/claims/${id}/status`).then(setClaim)}
      />
    </div>
  );
}
import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DetailHeader } from "@/components/ui/detail-header";
import { SectionHeading } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { EscalationFlagsCard } from "@/components/claim/EscalationFlagsCard";
import { DocumentsNeedingAttentionCard, type EvidenceIssue } from "@/components/claim/DocumentsNeedingAttentionCard";
import { ClaimAnalysisPanel } from "@/components/claim/ClaimAnalysisPanel";
import { ClaimSubmissionSummary, type ClaimDocumentItem, type ClaimSubmission } from "@/components/claim/ClaimSubmissionSummary";
import { AssignPolicyAgentModal } from "@/components/claim/AssignPolicyAgentModal";
import { ExpertReviewCard, type ExpertReview } from "@/components/claim/ExpertReviewCard";
import { ExpertRequestedDocumentsCard } from "@/components/claim/ExpertRequestedDocumentsCard";
import { InsightsPanel } from "@/components/claim/InsightsPanel";
import {
  PipelineTimeline,
  PIPELINE_STEPS,
  stepState,
  type TimelineEvent,
} from "@/components/claim/charts/PipelineTimeline";
import { apiJson, apiUrl, ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth";

interface Decision {
  claim_id: string;
  status: string;
  payable_amount: number;
  fraud_score: number;
  confidence_score: number;
  retrieved_clauses: string[];
  reasoning: string;
  human_review_required: boolean;
}

interface ClaimStatus {
  claim_id: string;
  id: number;
  status: string;
  claim_amount: number;
  escalation_flags?: string[];
  escalation_messages?: string[];
  assigned_agent?: string | null;
  assigned_at?: string | null;
  expert_review?: ExpertReview | null;
  evidence_mismatch?: boolean;
  evidence_issues?: EvidenceIssue[];
  pipeline_run_id?: number;
  decision?: Decision;
  submission?: ClaimSubmission;
  documents?: ClaimDocumentItem[];
}

interface ProgressEvent extends TimelineEvent {
  label: string;
  timestamp: string;
  data?: { from_step?: string };
}

interface InsightsData {
  timeline?: TimelineEvent[];
  [key: string]: unknown;
}

export function TrackClaim() {
  const { id } = useParams();
  const [claim, setClaim] = useState<ClaimStatus | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ok" | "not_found" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [liveLog, setLiveLog] = useState<string[]>([]);
  const [insights, setInsights] = useState<InsightsData | null>(null);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [sseKey, setSseKey] = useState(0);
  const streamRef = useRef<EventSource | null>(null);
  const notFoundRef = useRef(false);
  const docsCardRef = useRef<HTMLDivElement>(null);

  const refreshClaim = async () => {
    if (!id) return;
    const data = await apiJson<ClaimStatus>(`/api/claims/${id}/status`);
    setClaim(data);
    setLoadState("ok");
  };

  useEffect(() => {
    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;
    notFoundRef.current = false;

    const fetchClaim = async () => {
      try {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 15000);
        const data = await apiJson<ClaimStatus>(`/api/claims/${id}/status`, { signal: controller.signal });
        window.clearTimeout(timeout);
        if (cancelled) return;
        setClaim(data);
        setLoadError(null);
        setLoadState("ok");
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          notFoundRef.current = true;
          setLoadState("not_found");
          if (interval) clearInterval(interval);
          return;
        }
        const message =
          error instanceof DOMException && error.name === "AbortError"
            ? "The server took too long to respond. Restart the backend and try again."
            : error instanceof ApiError
              ? `Could not load claim (${error.status}).`
              : "Could not reach the API. Is the backend running on port 8000?";
        setLoadError(message);
        setLoadState("error");
      }
    };

    setLoadState("loading");
    setLoadError(null);
    setClaim(null);
    fetchClaim();
    interval = setInterval(() => {
      if (!notFoundRef.current) fetchClaim();
    }, 3000);

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [id]);

  useEffect(() => {
    if (loadState !== "ok") return;

    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    const fetchInsights = async () => {
      try {
        const data = await apiJson<InsightsData>(`/api/claims/${id}/insights`);
        if (!cancelled) setInsights(data);
      } catch (error) {
        if (!cancelled && error instanceof ApiError && error.status === 404) {
          if (interval) clearInterval(interval);
        }
      }
    };

    fetchInsights();
    interval = setInterval(fetchInsights, 3000);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [id, loadState]);

  useEffect(() => {
    const token = getToken();
    if (!id || !token || loadState !== "ok") return;

    const url = `${apiUrl(`/api/claims/${id}/stream`)}?token=${encodeURIComponent(token)}`;
    const source = new EventSource(url);
    streamRef.current = source;

    source.onmessage = (msg) => {
      try {
        const event: ProgressEvent = JSON.parse(msg.data);
        setEvents((prev) => {
          const exists = prev.some(
            (e) =>
              e.step === event.step &&
              e.status === event.status &&
              e.message === event.message &&
              e.timestamp === event.timestamp
          );
          return exists ? prev : [...prev, event];
        });
        if (event.step === "pipeline_reset") {
          setReprocessing(true);
        }
        if (event.step === "completed" && event.status === "completed") {
          setReprocessing(false);
        }
        setLiveLog((prev) => [...prev, `[${event.label}] ${event.message}`]);
      } catch (e) {
        console.error("SSE parse error", e);
      }
    };

    source.onerror = () => {
      source.close();
    };

    return () => {
      source.close();
      streamRef.current = null;
    };
  }, [id, loadState, sseKey]);

  useEffect(() => {
    if (claim?.status?.toUpperCase() === "PROCESSING" && reprocessing) {
      setSseKey((k) => k + 1);
    }
  }, [claim?.status, reprocessing]);

  if (loadState === "loading") {
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

  if (loadState === "error") {
    return (
      <Card>
        <CardContent className="mx-auto max-w-lg space-y-4 py-12 text-center">
          <h1 className="text-2xl font-semibold">Could not load claim</h1>
          <p className="text-muted-foreground">{loadError}</p>
          <div className="flex justify-center gap-3 pt-2">
            <Button onClick={() => window.location.reload()}>Retry</Button>
            <Link to="/history">
              <Button variant="outline">View claim history</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (loadState === "not_found" || !claim) {
    return (
      <Card>
        <CardContent className="mx-auto max-w-lg space-y-4 py-12 text-center">
          <h1 className="text-2xl font-semibold">Claim not found</h1>
          <p className="text-muted-foreground">
            Claim #{id} doesn&apos;t exist or isn&apos;t linked to your account.
            This can happen after a database reset — check History for your current claims.
          </p>
          <div className="flex justify-center gap-3 pt-2">
            <Link to="/history">
              <Button variant="outline">View claim history</Button>
            </Link>
            <Link to="/claim">
              <Button>File new claim</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  const decision = claim.decision;
  const processing = ["PENDING", "PROCESSING"].includes(claim.status.toUpperCase()) && !decision;
  const stuckProcessing = claim.status.toUpperCase() === "PROCESSING" && !decision;

  const retryProcessing = async () => {
    if (!id) return;
    try {
      await apiJson(`/api/claims/${id}/retry-processing`, { method: "POST" }, { json: true });
      setReprocessing(true);
      setSseKey((k) => k + 1);
      await refreshClaim();
    } catch (e) {
      console.error(e);
    }
  };
  const showDocumentsCard =
    claim.status.toUpperCase() === "PENDING_REVIEW" &&
    (claim.evidence_mismatch ||
      (claim.escalation_flags?.includes("low_evidence_confidence") ?? false)) &&
    (claim.evidence_issues?.filter((i) => !i.acknowledged).length ?? 0) > 0;
  const completedSteps = PIPELINE_STEPS.filter((s) => stepState(s, [...events, ...(insights?.timeline || [])]) === "completed").length;

  return (
    <div className="space-y-6 pb-8">
      <DetailHeader
        back={{ to: "/history", label: "All claims" }}
        eyebrow="Claim tracking"
        title={`Claim ${claim.claim_id}`}
        subtitle={`${processing ? "Review in progress" : "Review complete"} · ₹${claim.claim_amount?.toLocaleString("en-IN")} claimed`}
        status={<ClaimStatusBadge status={claim.status} assignedAgent={claim.assigned_agent} />}
        meta={[
          {
            label: "Pipeline progress",
            value: `${completedSteps} of ${PIPELINE_STEPS.length} steps`,
          },
        ]}
      />

      {claim.expert_review && (
        <ExpertReviewCard review={claim.expert_review} assignedAt={claim.assigned_at} variant="inline" />
      )}

      {claim.expert_review?.requested_documents &&
        claim.expert_review.requested_documents.length > 0 &&
        id && (
          <ExpertRequestedDocumentsCard
            claimId={id}
            requestedDocuments={claim.expert_review.requested_documents}
            disabled={claim.status.toUpperCase() === "PROCESSING" || reprocessing}
            onUploaded={refreshClaim}
          />
        )}

      {claim.submission && id && (
        <ClaimSubmissionSummary
          claimId={id}
          submission={claim.submission}
          documents={claim.documents}
          claimAmount={claim.claim_amount}
        />
      )}

      <SectionHeading
        title="AI insights & analysis"
        description="AI-powered insights, scores, and recommendations for your claim."
        className="border-t pt-6"
      />

      {/* Content grid: main + insights sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        {/* Main column */}
        <div className="space-y-4 min-w-0">
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle>Claim review progress</CardTitle>
                  <CardDescription>Step-by-step updates as we review your claim</CardDescription>
                </div>
                {stuckProcessing && (
                  <Button type="button" size="sm" variant="outline" onClick={retryProcessing}>
                    Retry processing
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <PipelineTimeline
                events={events}
                timeline={insights?.timeline}
                resetFromStep={reprocessing ? "evidence_analysis" : undefined}
              />
            </CardContent>
          </Card>

          {decision && (
            <ClaimAnalysisPanel
              analysis={decision}
              claimId={claim.claim_id}
              status={claim.status}
              onContinue={(action) => {
                const lower = action.toLowerCase();
                if (lower.includes("upload") || lower.includes("document")) {
                  if (showDocumentsCard) {
                    docsCardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
                    return true;
                  }
                }
                if (lower.includes("expert")) {
                  setAssignModalOpen(true);
                  return true;
                }
                return false;
              }}
            />
          )}

          {showDocumentsCard && id && (
            <div ref={docsCardRef}>
              <DocumentsNeedingAttentionCard
                claimId={id}
                issues={claim.evidence_issues ?? []}
                disabled={claim.status.toUpperCase() === "PROCESSING" || reprocessing}
                onReprocessing={() => {
                  setReprocessing(true);
                  setSseKey((k) => k + 1);
                }}
                onUpdated={refreshClaim}
              />
            </div>
          )}

          {((claim.escalation_messages?.length ?? 0) > 0 ||
            (claim.escalation_flags?.length ?? 0) > 0) && (
            <EscalationFlagsCard
              messages={claim.escalation_messages ?? []}
              flags={claim.escalation_flags}
              assignedAgent={claim.assigned_agent}
              onAssign={() => setAssignModalOpen(true)}
            />
          )}

          {liveLog.length > 0 && (
            <Card className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Review activity</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="font-mono text-xs space-y-0.5 max-h-48 overflow-y-auto bg-muted p-3 rounded-md">
                  {liveLog.slice(-20).map((line, i) => (
                    <div key={i} className="text-muted-foreground">{line}</div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Insights sidebar — charts only */}
        <div className="min-w-0">
          <Card className="shadow-sm lg:sticky lg:top-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Insights</CardTitle>
              <CardDescription className="text-xs">Coverage, scores, and payout analysis</CardDescription>
            </CardHeader>
            <CardContent className="max-h-[calc(100vh-8rem)] overflow-y-auto">
              <InsightsPanel insights={insights as never} />
            </CardContent>
          </Card>
        </div>
      </div>

      {id && (
        <AssignPolicyAgentModal
          claimId={id}
          open={assignModalOpen}
          onClose={() => setAssignModalOpen(false)}
          onAssigned={refreshClaim}
        />
      )}
    </div>
  );
}

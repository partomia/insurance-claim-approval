import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { DetailHeader } from "@/components/ui/detail-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ClaimAnalysisPanel, type AIAnalysis } from "@/components/claim/ClaimAnalysisPanel";
import { ClaimSubmissionSummary, type ClaimDocumentItem, type ClaimSubmission } from "@/components/claim/ClaimSubmissionSummary";
import { AlertTriangle, ExternalLink, FileWarning, User } from "lucide-react";
import { InsightsPanel } from "@/components/claim/InsightsPanel";
import { ExpertPolicyRequirements } from "@/components/agent/ExpertPolicyRequirements";
import { agentApiFetch, agentApiJson } from "@/lib/agentApi";
import { openAgentClaimDocument } from "@/lib/agentDocuments";
import { formatApiError, useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import { EXPERT_DOCUMENT_TYPES } from "@/lib/documentTypes";

interface ClaimStatus {
  claim_id: string;
  id: number;
  customer_id?: number;
  status: string;
  claim_amount: number;
  escalation_flags?: string[];
  escalation_messages?: string[];
  assigned_agent?: string | null;
  evidence_issues?: Array<{
    field: string;
    document_id: number;
    filename: string;
    reason: string;
    issue_code: string;
    acknowledged?: boolean;
  }>;
  decision?: AIAnalysis & Record<string, unknown>;
  submission?: ClaimSubmission;
  documents?: ClaimDocumentItem[];
}

const CHECKLIST = [
  "All mandatory documents uploaded",
  "Policy clause coverage confirmed with customer",
  "Invoice and medical records verified",
  "Customer understands next steps with insurer",
];

export function AgentClaimReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { success, error } = useToast();
  const [claim, setClaim] = useState<ClaimStatus | null>(null);
  const [insights, setInsights] = useState<Record<string, unknown> | null>(null);
  const [notes, setNotes] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [checked, setChecked] = useState<string[]>([]);
  const [selectedDocTypes, setSelectedDocTypes] = useState<string[]>([]);
  const [customDocLabel, setCustomDocLabel] = useState("");
  const [customDocs, setCustomDocs] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      agentApiJson<ClaimStatus>(`/api/agent/claims/${id}`),
      agentApiJson<Record<string, unknown>>(`/api/agent/claims/${id}/insights`).catch(() => null),
    ])
      .then(([claimData, insightsData]) => {
        setClaim(claimData);
        setInsights(insightsData);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setLoadError("Claim not found or not assigned to you.");
        else setLoadError("Could not load claim.");
      });
  }, [id]);

  const submitConsultation = async (action: "SUBMISSION_READY" | "NEEDS_IMPROVEMENT" | "CONTINUE_REVIEW") => {
    if (!id) return;

    const requestedDocuments = [...selectedDocTypes, ...customDocs];
    if (action === "NEEDS_IMPROVEMENT" && requestedDocuments.length === 0) {
      error("Select at least one document the customer must upload.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await agentApiFetch(
        `/api/agent/claims/${id}/consult`,
        {
          method: "POST",
          body: JSON.stringify({
            action,
            reviewer_notes: notes,
            checklist: checked,
            internal_notes: internalNotes,
            requested_documents: action === "NEEDS_IMPROVEMENT" ? requestedDocuments : [],
          }),
        },
        { json: true }
      );
      if (res.ok) {
        success(action === "SUBMISSION_READY" ? "Marked submission-ready for customer." : "Consultation updated.");
        navigate("/agent/claims");
      } else {
        error(formatApiError((await res.json()).detail));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submitToInsurer = async () => {
    if (!id) return;
    setSubmitting(true);
    try {
      const res = await agentApiFetch(`/api/agent/claims/${id}/submit-to-insurer`, { method: "POST" });
      if (res.ok) {
        success("Claim submitted to insurance company on customer's behalf.");
        navigate("/agent/claims");
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
          <Button variant="outline" onClick={() => navigate("/agent/claims")}>Back to claims queue</Button>
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

  const canConsult = ["PENDING_REVIEW", "REQUEST_MORE_INFO", "HUMAN_REVIEW", "ANALYSIS_COMPLETE"].includes(claim.status);
  const canSubmit = claim.status === "SUBMISSION_READY";
  const showDocIssues = (claim.evidence_issues?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <DetailHeader
        back={{ to: "/agent/claims", label: "Claims queue" }}
        eyebrow="Claim consultation workspace"
        title={claim.claim_id}
        subtitle="Review submission, documents, policy requirements, and AI analysis."
        status={<ClaimStatusBadge status={claim.status} />}
        actions={
          <Link to={`/agent/claims/${id}/audit`}>
            <Button variant="outline" size="sm">Audit trail</Button>
          </Link>
        }
      />

      {claim.submission && id && (
        <ClaimSubmissionSummary
          claimId={id}
          submission={claim.submission}
          documents={claim.documents}
          claimAmount={claim.claim_amount}
          openDocument={(doc) => openAgentClaimDocument(id, doc.id, doc.filename)}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        <div className="space-y-6 min-w-0">
          <ClaimAnalysisPanel analysis={claim.decision ?? null} claimId={claim.claim_id} status={claim.status} />

          {id && <ExpertPolicyRequirements claimId={Number(id)} />}

          {showDocIssues && id && (
            <Card className="shadow-sm ring-warning-border bg-warning-subtle">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <FileWarning className="w-5 h-5 text-warning" />
                  <CardTitle className="text-base">Documents Needing Attention</CardTitle>
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
                        onClick={() => openAgentClaimDocument(id, issue.document_id, issue.filename)}
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

          {claim.customer_id && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <User className="h-4 w-4" />
                  Customer
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Link to={`/agent/customers/${claim.customer_id}`} className="text-sm text-primary hover:underline">
                  View customer profile →
                </Link>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle className="text-base">Consultation Checklist</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {CHECKLIST.map((item) => (
                <label key={item} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={checked.includes(item)}
                    onChange={(e) =>
                      setChecked((prev) => (e.target.checked ? [...prev, item] : prev.filter((x) => x !== item)))
                    }
                  />
                  {item}
                </label>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Message to Customer</CardTitle></CardHeader>
            <CardContent>
              <Textarea
                placeholder="Recommendations visible to the customer..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Internal Notes</CardTitle></CardHeader>
            <CardContent>
              <Textarea
                className="min-h-[80px]"
                placeholder="Private notes (not shown to customer)"
                value={internalNotes}
                onChange={(e) => setInternalNotes(e.target.value)}
              />
            </CardContent>
          </Card>

          {canConsult && (
            <Card>
              <CardHeader><CardTitle className="text-base">Expert Actions</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-lg border bg-muted/30 p-3 space-y-3">
                  <p className="text-sm font-medium">Documents to request from customer</p>
                  <p className="text-xs text-muted-foreground">
                    Required when requesting more documents. Selected items appear as upload fields on the customer&apos;s claim page.
                  </p>
                  <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                    {EXPERT_DOCUMENT_TYPES.map((doc) => (
                      <label key={doc.value} className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={selectedDocTypes.includes(doc.value)}
                          onChange={(e) =>
                            setSelectedDocTypes((prev) =>
                              e.target.checked ? [...prev, doc.value] : prev.filter((v) => v !== doc.value)
                            )
                          }
                        />
                        <span>{doc.label}</span>
                      </label>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
                      placeholder="Custom document (e.g. Lab reports)"
                      value={customDocLabel}
                      onChange={(e) => setCustomDocLabel(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          const label = customDocLabel.trim();
                          if (label && !customDocs.includes(label)) {
                            setCustomDocs((prev) => [...prev, label]);
                            setCustomDocLabel("");
                          }
                        }
                      }}
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const label = customDocLabel.trim();
                        if (!label) return;
                        if (!customDocs.includes(label)) {
                          setCustomDocs((prev) => [...prev, label]);
                        }
                        setCustomDocLabel("");
                      }}
                    >
                      Add
                    </Button>
                  </div>
                  {customDocs.length > 0 && (
                    <ul className="flex flex-wrap gap-2">
                      {customDocs.map((label) => (
                        <li
                          key={label}
                          className="inline-flex items-center gap-1 rounded-full border bg-background px-2 py-1 text-xs"
                        >
                          {label}
                          <button
                            type="button"
                            className="text-muted-foreground hover:text-foreground"
                            onClick={() => setCustomDocs((prev) => prev.filter((x) => x !== label))}
                            aria-label={`Remove ${label}`}
                          >
                            ×
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <Button className="w-full" disabled={submitting} onClick={() => submitConsultation("SUBMISSION_READY")}>
                  Mark Submission Ready
                </Button>
                <Button variant="outline" className="w-full" disabled={submitting} onClick={() => submitConsultation("NEEDS_IMPROVEMENT")}>
                  Request More Documents
                </Button>
                <Button variant="ghost" className="w-full" disabled={submitting} onClick={() => submitConsultation("CONTINUE_REVIEW")}>
                  Continue Review
                </Button>
              </CardContent>
            </Card>
          )}

          {canSubmit && (
            <Card>
              <CardHeader><CardTitle className="text-base">Submit to Insurer</CardTitle></CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-3">Customer claim is ready. Submit to their insurance company.</p>
                <Button className="w-full" disabled={submitting} onClick={submitToInsurer}>
                  Submit to Insurance Company
                </Button>
              </CardContent>
            </Card>
          )}

        </div>
      </div>
    </div>
  );
}

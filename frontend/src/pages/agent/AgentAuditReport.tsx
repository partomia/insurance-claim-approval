import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DetailHeader } from "@/components/ui/detail-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ChatMarkdown } from "@/components/claim/ChatMarkdown";
import { agentApiJson } from "@/lib/agentApi";
import { formatEscalationList } from "@/lib/escalationLabels";
import { openAgentClaimDocument } from "@/lib/agentDocuments";
import { useToast } from "@/components/ui/toast";
import { ExternalLink, FileText } from "lucide-react";

interface AuditReportData {
  claim_id: string;
  claim_number: string;
  status: string;
  claim_details?: {
    incident_description: string;
    incident_datetime: string;
    location: string;
    claim_amount: number;
    customer_name: string;
    policy_number?: string | null;
    policy_type?: string | null;
  };
  decision?: Record<string, unknown>;
  fraud_assessment?: Record<string, unknown>;
  evidence_issues?: Array<{
    field: string;
    document_id: number;
    filename: string;
    reason: string;
    issue_code: string;
  }>;
  evidence_results?: Array<Record<string, unknown>>;
  escalation_flags?: string[];
  escalation_messages?: string[];
  audit_trail?: Array<Record<string, string>>;
  documents?: Array<{ id: number; filename: string; doc_type: string; uploaded_at?: string }>;
}

export function AgentAuditReport() {
  const { id } = useParams();
  const { error } = useToast();
  const [report, setReport] = useState<AuditReportData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<number | null>(null);

  useEffect(() => {
    if (!id) return;
    agentApiJson<AuditReportData>(`/api/agent/claims/${id}/audit`)
      .then(setReport)
      .catch(() => setLoadError("Audit report unavailable."));
  }, [id]);

  if (loadError) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <p className="font-medium">{loadError}</p>
          <Link to={`/agent/claims/${id}`}>
            <Button variant="outline">Back to claim review</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  if (!report) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36" />
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const details = report.claim_details;
  const documents = report.documents ?? [];

  return (
    <div className="space-y-6">
      <DetailHeader
        back={{ to: `/agent/claims/${id}`, label: "Back to claim review" }}
        eyebrow="Audit report"
        title={`Audit — ${report.claim_number}`}
        subtitle="Regulator-ready compliance record"
        status={<ClaimStatusBadge status={report.status} />}
      />

      {details && (
        <Card>
          <CardHeader>
            <CardTitle>Claim Details</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <p><span className="text-muted-foreground">Customer:</span> {details.customer_name}</p>
            <p><span className="text-muted-foreground">Amount:</span> ${details.claim_amount.toLocaleString()}</p>
            <p><span className="text-muted-foreground">Location:</span> {details.location}</p>
            <p><span className="text-muted-foreground">Incident:</span> {details.incident_description}</p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4" />
            Uploaded Documents ({documents.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents on file.</p>
          ) : (
            <ul className="space-y-3">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="rounded-md border bg-muted/30 px-3 py-2.5 text-sm flex flex-col sm:flex-row sm:items-center gap-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-xs text-primary uppercase tracking-wide">{doc.doc_type}</p>
                    <p className="mt-0.5 break-all">{doc.filename}</p>
                  </div>
                  {id && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 self-start"
                      disabled={openingId === doc.id}
                      onClick={async () => {
                        setOpeningId(doc.id);
                        try {
                          await openAgentClaimDocument(id, doc.id, doc.filename);
                        } catch (e) {
                          error(e instanceof Error ? e.message : "Could not open document");
                        } finally {
                          setOpeningId(null);
                        }
                      }}
                    >
                      <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                      {openingId === doc.id ? "Opening..." : "View"}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {typeof report.decision?.reasoning === "string" && report.decision.reasoning && (
        <Card>
          <CardHeader>
            <CardTitle>Decision Reasoning</CardTitle>
          </CardHeader>
          <CardContent>
            <ChatMarkdown content={report.decision.reasoning} />
          </CardContent>
        </Card>
      )}

      {(report.evidence_results?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Evidence Validation</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.evidence_results!.map((ev, i) => (
                <div key={i} className="text-sm border rounded-md p-3">
                  <p className="font-medium">{String(ev.filename ?? ev.doc_type ?? "Document")}</p>
                  <p className="text-muted-foreground text-xs mt-1">
                    Confidence:{" "}
                    {ev.confidence != null
                      ? `${(Number(ev.confidence) * 100).toFixed(0)}%`
                      : ev.valid
                        ? "Valid"
                        : "Review needed"}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {report.evidence_issues && report.evidence_issues.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Evidence Issues</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {report.evidence_issues.map((issue, i) => (
              <div key={i} className="border rounded p-2">
                <p className="font-medium">{issue.filename} — {issue.field}</p>
                <p className="text-muted-foreground">{issue.reason}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {formatEscalationList(report.escalation_messages, report.escalation_flags).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Needs your attention</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="text-sm space-y-1 list-disc list-inside">
              {formatEscalationList(report.escalation_messages, report.escalation_flags).map((msg) => (
                <li key={msg}>{msg}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {report.audit_trail && report.audit_trail.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Audit Trail</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {report.audit_trail.map((entry, i) => (
                <li key={i} className="border-b pb-2 last:border-0">
                  <span className="font-medium">{entry.action ?? entry.event_type}</span>
                  {entry.actor && <span className="text-muted-foreground"> · {entry.actor}</span>}
                  {entry.timestamp && (
                    <span className="text-muted-foreground text-xs block">{entry.timestamp}</span>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

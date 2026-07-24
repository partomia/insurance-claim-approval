import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { FileText, MapPin, User, Calendar, DollarSign, Shield, ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DetailHeader } from "@/components/ui/detail-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ChatMarkdown } from "@/components/claim/ChatMarkdown";
import { apiJson } from "@/lib/api";
import { openClaimDocument } from "@/lib/documents";
import { formatEscalationList } from "@/lib/escalationLabels";
import { useToast } from "@/components/ui/toast";

interface ClaimDetails {
  incident_description: string;
  incident_datetime: string;
  location: string;
  claim_amount: number;
  customer_name: string;
  policy_number?: string | null;
  policy_type?: string | null;
}

interface UploadedDocument {
  id: number;
  doc_type: string;
  filename: string;
  uploaded_at: string;
}

interface EvidenceIssue {
  field: string;
  document_id: number;
  filename: string;
  reason: string;
  issue_code: string;
  acknowledged: boolean;
}

interface AuditReportData {
  claim_id: string;
  claim_number: string;
  status: string;
  claim_details?: ClaimDetails;
  documents?: UploadedDocument[];
  escalation_flags?: string[];
  escalation_messages?: string[];
  evidence_issues?: EvidenceIssue[];
  decision?: Record<string, unknown>;
  fraud_assessment?: Record<string, unknown>;
  evidence_results?: Array<Record<string, unknown>>;
  retrieved_clauses?: Array<Record<string, unknown>>;
  audit_trail?: Array<Record<string, string>>;
  generated_at?: string;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  GOV_ID: "Government ID",
  PROOF: "Proof document",
  POLICE_REPORT: "Police report",
  MEDICAL: "Medical",
  INVOICE: "Invoice",
  POLICY_PAPER: "Policy paper",
  OTHER: "Other",
};

function formatDocType(type: string): string {
  return DOC_TYPE_LABELS[type] || type.replace(/_/g, " ");
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function AuditReport() {
  const { id } = useParams();
  const { error } = useToast();
  const [report, setReport] = useState<AuditReportData | null>(null);
  const [openingId, setOpeningId] = useState<number | null>(null);

  useEffect(() => {
    const fetchAudit = async () => {
      try {
        const data = await apiJson<AuditReportData>(`/api/claims/${id}/audit`);
        setReport(data);
      } catch (error) {
        console.error("Error fetching audit:", error);
      }
    };
    fetchAudit();
  }, [id]);

  if (!report) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36" />
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  const decision = report.decision;
  const fraudAssessment = report.fraud_assessment;
  const auditTrail = report.audit_trail;
  const details = report.claim_details;
  const documents = report.documents ?? [];

  return (
    <div className="space-y-6 pb-8">
      <DetailHeader
        back={{ to: `/track/${id}`, label: "Back to claim" }}
        eyebrow="Audit report"
        title={`Audit — ${report.claim_number}`}
        subtitle="Regulator-ready compliance record"
        status={<ClaimStatusBadge status={report.status} />}
        actions={
          <Link to={`/track/${id}`}>
            <Button variant="outline" size="sm">Track claim</Button>
          </Link>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6 items-start">
        {/* Left panel — claim details & documents */}
        <div className="space-y-4 lg:sticky lg:top-4">
          {details && (
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Claim Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-start gap-2">
                  <User className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-muted-foreground">Customer</p>
                    <p className="font-medium">{details.customer_name}</p>
                  </div>
                </div>
                {details.policy_number && (
                  <div className="flex items-start gap-2">
                    <Shield className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                    <div>
                      <p className="text-xs text-muted-foreground">Policy</p>
                      <p className="font-medium">
                        {details.policy_number}
                        {details.policy_type ? ` (${details.policy_type})` : ""}
                      </p>
                    </div>
                  </div>
                )}
                <div className="flex items-start gap-2">
                  <DollarSign className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-muted-foreground">Claim amount</p>
                    <p className="font-medium">${details.claim_amount.toLocaleString()}</p>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <Calendar className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-muted-foreground">Incident date</p>
                    <p className="font-medium">{formatDate(details.incident_datetime)}</p>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <MapPin className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-muted-foreground">Location</p>
                    <p className="font-medium">{details.location}</p>
                  </div>
                </div>
                <div className="pt-1 border-t">
                  <p className="text-xs text-muted-foreground mb-1">Incident description</p>
                  <p className="leading-relaxed">{details.incident_description}</p>
                </div>
              </CardContent>
            </Card>
          )}

          <Card className="shadow-sm">
            <CardHeader className="pb-3">
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
                        <p className="font-medium text-xs text-primary uppercase tracking-wide">
                          {formatDocType(doc.doc_type)}
                        </p>
                        <p className="mt-0.5 break-all">{doc.filename}</p>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          {formatDate(doc.uploaded_at)}
                        </p>
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
                              await openClaimDocument(id, doc.id, doc.filename);
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

          {formatEscalationList(report.escalation_messages, report.escalation_flags).length > 0 && (
            <Card className="shadow-sm ring-warning-border">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Needs your attention</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="text-sm space-y-1 list-disc list-inside text-warning">
                  {formatEscalationList(report.escalation_messages, report.escalation_flags).map((msg) => (
                    <li key={msg}>{msg}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Main content */}
        <div className="space-y-4 min-w-0">
          {decision && (
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>Decision Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="text-xs text-muted-foreground">Status</p>
                    <p className="font-semibold">{String(decision.status ?? "—")}</p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="text-xs text-muted-foreground">Confidence</p>
                    <p className="font-semibold">
                      {decision.confidence_score != null
                        ? `${(Number(decision.confidence_score) * 100).toFixed(1)}%`
                        : "—"}
                    </p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="text-xs text-muted-foreground">Fraud score</p>
                    <p className="font-semibold">
                      {decision.fraud_score != null
                        ? `${(Number(decision.fraud_score) * 100).toFixed(1)}%`
                        : "—"}
                    </p>
                  </div>
                </div>
                {decision.reasoning != null && (
                  <div>
                    <p className="text-sm text-muted-foreground mb-1">AI reasoning</p>
                    <div className="text-sm p-3 bg-muted rounded-md">
                      <ChatMarkdown content={String(decision.reasoning)} />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {fraudAssessment && (
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>Fraud Assessment</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-sm bg-muted p-4 rounded overflow-auto">
                  {JSON.stringify(fraudAssessment, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

          {(report.evidence_results?.length ?? 0) > 0 && (
            <Card className="shadow-sm">
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

          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle>Audit Trail ({auditTrail?.length || 0} events)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {auditTrail?.map((event, i) => (
                  <div key={i} className="border-l-2 border-primary pl-4 py-2">
                    <div className="font-medium">{event.event_type}</div>
                    <div className="text-sm text-muted-foreground">
                      {event.timestamp} — {event.actor}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import {
  Calendar,
  IndianRupee,
  ExternalLink,
  FileText,
  MapPin,
  Shield,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { openClaimDocument } from "@/lib/documents";
import { useToast } from "@/components/ui/toast";
import { formatINR } from "@/lib/currency";

export interface ClaimSubmission {
  incident_description: string;
  incident_datetime: string;
  location: string;
  policy_number?: string | null;
  policy_type?: string | null;
}

export interface ClaimDocumentItem {
  id: number;
  doc_type: string;
  filename: string;
  uploaded_at: string;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  DRIVER_LICENSE: "Driver's licence",
  DAMAGE_PHOTO: "Damage photo",
  REPAIR_ESTIMATE: "Repair estimate",
  POLICE_REPORT: "Police / FIR report",
  VEHICLE_REGISTRATION: "Vehicle registration (RC)",
  TOWING_INVOICE: "Towing invoice",
  THIRD_PARTY_STATEMENT: "Third-party statement",
  POLICY_PAPER: "Policy paper",
  OTHER: "Other",
};

const DOC_TYPE_BADGE: Record<string, string> = {
  DAMAGE_PHOTO: "bg-info-subtle text-info",
  REPAIR_ESTIMATE: "bg-secondary/10 text-secondary",
  DRIVER_LICENSE: "bg-warning-subtle text-warning",
  VEHICLE_REGISTRATION: "bg-warning-subtle text-warning",
  POLICE_REPORT: "bg-muted text-foreground",
  TOWING_INVOICE: "bg-secondary/10 text-secondary",
  THIRD_PARTY_STATEMENT: "bg-muted text-foreground",
  POLICY_PAPER: "bg-success-subtle text-success",
  OTHER: "bg-muted text-muted-foreground",
};

function formatDocType(type: string): string {
  return DOC_TYPE_LABELS[type] || type.replace(/_/g, " ");
}

function docBadgeClass(type: string): string {
  return DOC_TYPE_BADGE[type] || DOC_TYPE_BADGE.OTHER;
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StatTile({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Shield;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-3 shadow-sm">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <p className="text-[11px] font-medium uppercase tracking-wide">{label}</p>
      </div>
      <p className="text-sm font-semibold leading-snug">{value}</p>
    </div>
  );
}

interface ClaimSubmissionSummaryProps {
  claimId: string | number;
  submission: ClaimSubmission;
  documents?: ClaimDocumentItem[];
  claimAmount?: number;
  openDocument?: (doc: ClaimDocumentItem) => Promise<void>;
}

export function ClaimSubmissionSummary({
  claimId,
  submission,
  documents = [],
  claimAmount,
  openDocument,
}: ClaimSubmissionSummaryProps) {
  const { error } = useToast();
  const [openingId, setOpeningId] = useState<number | null>(null);

  const handleView = async (doc: ClaimDocumentItem) => {
    setOpeningId(doc.id);
    try {
      if (openDocument) {
        await openDocument(doc);
      } else {
        await openClaimDocument(claimId, doc.id, doc.filename);
      }
    } catch (e) {
      error(e instanceof Error ? e.message : "Could not open document");
    } finally {
      setOpeningId(null);
    }
  };

  const policyLabel = submission.policy_number
    ? `${submission.policy_number}${submission.policy_type ? ` (${submission.policy_type})` : ""}`
    : "—";

  return (
    <section className="rounded-2xl border-2 border-primary/15 bg-primary/[0.03] p-4 md:p-5 space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-primary">Your submission</p>
        <p className="text-sm text-muted-foreground mt-0.5">
          What you filed — review before comparing with AI analysis below.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="shadow-md border-border/80">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Motor claim request</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <StatTile icon={Shield} label="Policy" value={policyLabel} />
              <StatTile
                icon={IndianRupee}
                label="Amount"
                value={claimAmount != null ? formatINR(Number(claimAmount)) : "—"}
              />
              <StatTile icon={Calendar} label="Incident date" value={formatDate(submission.incident_datetime)} />
              <StatTile icon={MapPin} label="Location" value={submission.location} />
            </div>

            <div className="rounded-r-lg border-l-4 border-primary bg-muted/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary mb-2">
                What you reported
              </p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap text-foreground">
                {submission.incident_description}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-md border-border/80">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <FileText className="w-4 h-4" />
              Submitted documents ({documents.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {documents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No documents uploaded for this claim.</p>
            ) : (
              <ul className="space-y-3">
                {documents.map((doc) => (
                  <li
                    key={doc.id}
                    className="flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border bg-card p-3 shadow-sm"
                  >
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${docBadgeClass(doc.doc_type)}`}
                      >
                        {formatDocType(doc.doc_type)}
                      </span>
                      <p className="text-sm font-medium break-all">{doc.filename}</p>
                      <p className="text-xs text-muted-foreground">{formatDate(doc.uploaded_at)}</p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 self-start sm:self-center"
                      disabled={openingId === doc.id}
                      onClick={() => handleView(doc)}
                    >
                      <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                      {openingId === doc.id ? "Opening..." : "View"}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
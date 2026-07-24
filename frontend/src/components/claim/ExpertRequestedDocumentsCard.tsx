import { useState } from "react";
import { CheckCircle2, FileUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FileInput } from "@/components/ui/file-input";
import { uploadClaimDocument } from "@/lib/supplementalUpload";
import { useToast } from "@/components/ui/toast";
import type { ExpertRequestedDocument } from "@/components/claim/ExpertReviewCard";

interface ExpertRequestedDocumentsCardProps {
  claimId: string;
  requestedDocuments: ExpertRequestedDocument[];
  disabled?: boolean;
  onUploaded: () => void;
}

const fileInputClassName =
  "[&_button]:min-h-[72px] [&_button]:border-2 [&_button]:border-dashed [&_button]:border-input [&_button]:bg-field [&_button]:shadow-none";

export function ExpertRequestedDocumentsCard({
  claimId,
  requestedDocuments,
  disabled = false,
  onUploaded,
}: ExpertRequestedDocumentsCardProps) {
  const { error, success } = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<Record<string, File>>({});

  if (requestedDocuments.length === 0) return null;

  const pending = requestedDocuments.filter((doc) => !doc.fulfilled);

  const handleUpload = async (doc: ExpertRequestedDocument) => {
    const file = pendingFiles[doc.id];
    if (!file) {
      error("Choose a file to upload first.");
      return;
    }

    setBusyId(doc.id);
    try {
      await uploadClaimDocument(claimId, doc.document_type, [file]);
      success(`${doc.label} uploaded — your expert will be notified.`);
      setPendingFiles((prev) => {
        const next = { ...prev };
        delete next[doc.id];
        return next;
      });
      onUploaded();
    } catch (e) {
      error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="rounded-xl border border-l-4 border-l-warning bg-card shadow-sm">
      <div className="p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-warning/15 text-warning">
            <Upload className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold">
              Documents requested by your expert
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Upload each item below so your Claim Expert can continue review.
            </p>
          </div>
          {pending.length > 0 && (
            <span className="shrink-0 rounded-md bg-warning px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-warning-foreground">
              {pending.length} pending
            </span>
          )}
        </div>

        <div className="space-y-3">
          {requestedDocuments.map((doc) => (
            <div
              key={doc.id}
              className={
                doc.fulfilled
                  ? "rounded-lg border border-success-border bg-success-subtle p-4"
                  : "rounded-lg border bg-muted/40 p-4"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{doc.label}</p>
                  <p
                    className={
                      doc.fulfilled
                        ? "mt-0.5 text-xs text-success"
                        : "mt-0.5 text-xs text-muted-foreground"
                    }
                  >
                    {doc.fulfilled ? "Uploaded — thank you" : "Required to continue review"}
                  </p>
                </div>
                {doc.fulfilled ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
                ) : (
                  <FileUp className="h-5 w-5 shrink-0 text-warning" />
                )}
              </div>

              {!doc.fulfilled && (
                <div className="mt-3 space-y-3 border-t pt-3">
                  <FileInput
                    accept=".pdf,.png,.jpg,.jpeg"
                    placeholder={busyId === doc.id ? "Uploading…" : `Choose ${doc.label.toLowerCase()}`}
                    disabled={disabled || busyId === doc.id}
                    className={fileInputClassName}
                    onFilesSelected={(files) => {
                      const file = files[0];
                      if (file) {
                        setPendingFiles((prev) => ({ ...prev, [doc.id]: file }));
                      }
                    }}
                  />
                  {pendingFiles[doc.id] && (
                    <p className="truncate text-xs text-muted-foreground">
                      Selected: {pendingFiles[doc.id].name}
                    </p>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    disabled={disabled || busyId === doc.id || !pendingFiles[doc.id]}
                    variant={pendingFiles[doc.id] ? "default" : "outline"}
                    onClick={() => handleUpload(doc)}
                  >
                    {busyId === doc.id ? "Uploading…" : "Upload document"}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>

        {pending.length === 0 && (
          <p className="rounded-lg border border-success-border bg-success-subtle px-3 py-2 text-sm font-medium text-success">
            All requested documents are uploaded. Your expert will continue review shortly.
          </p>
        )}
      </div>
    </section>
  );
}

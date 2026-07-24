import { useState } from "react";
import { AlertTriangle, FileWarning } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FileInput } from "@/components/ui/file-input";
import {
  acknowledgeEvidenceDocument,
  replaceEvidenceDocument,
} from "@/lib/evidenceUpload";
import { useToast } from "@/components/ui/toast";

export interface EvidenceIssue {
  field: string;
  document_id: number;
  filename: string;
  reason: string;
  issue_code: string;
  acknowledged: boolean;
}

interface DocumentsNeedingAttentionCardProps {
  claimId: string;
  issues: EvidenceIssue[];
  disabled?: boolean;
  onReprocessing: (pipelineRunId: number) => void;
  onUpdated: () => void;
}

export function DocumentsNeedingAttentionCard({
  claimId,
  issues,
  disabled = false,
  onReprocessing,
  onUpdated,
}: DocumentsNeedingAttentionCardProps) {
  const { error, success } = useToast();
  const [busyId, setBusyId] = useState<number | null>(null);

  const openIssues = issues.filter((i) => !i.acknowledged);
  if (openIssues.length === 0) return null;

  const handleReplace = async (documentId: number, file: File) => {
    setBusyId(documentId);
    try {
      const result = await replaceEvidenceDocument(claimId, file, documentId);
      success("Document replaced — re-analyzing evidence.");
      onReprocessing(result.pipeline_run_id);
      onUpdated();
    } catch (e) {
      error(e instanceof Error ? e.message : "Replace failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleAcknowledge = async (documentId: number) => {
    const note = window.prompt(
      "Optional note — why are you keeping this document as-is?",
      ""
    );
    if (note === null) return;

    setBusyId(documentId);
    try {
      const result = await acknowledgeEvidenceDocument(claimId, documentId, note || undefined);
      success(result.message);
      if (result.pipeline_run_id) {
        onReprocessing(result.pipeline_run_id);
      }
      onUpdated();
    } catch (e) {
      error(e instanceof Error ? e.message : "Acknowledge failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card className="shadow-sm ring-warning-border bg-warning-subtle">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <FileWarning className="w-5 h-5 text-warning" />
          <CardTitle className="text-base">Documents Needing Attention</CardTitle>
        </div>
        <CardDescription>
          One or more uploaded documents may not match what we expected. Replace them or keep as-is to continue review.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {openIssues.map((issue) => (
          <div
            key={`${issue.document_id}-${issue.issue_code}`}
            className="rounded-lg border bg-background p-4 space-y-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-warning mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-sm">{issue.field}</p>
                <p className="text-xs text-muted-foreground truncate">{issue.filename}</p>
                <p className="text-sm mt-1">{issue.reason}</p>
              </div>
            </div>

            <FileInput
              accept=".pdf,.png,.jpg,.jpeg"
              placeholder={busyId === issue.document_id ? "Uploading..." : "Replace with a new file"}
              disabled={disabled || busyId === issue.document_id}
              className="[&_button]:min-h-[72px]"
              onFilesSelected={(files) => {
                const file = files[0];
                if (file) handleReplace(issue.document_id, file);
              }}
            />

            <div className="flex flex-wrap gap-2 pt-1 border-t">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || busyId === issue.document_id}
                onClick={() => handleAcknowledge(issue.document_id)}
              >
                Keep As-Is
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

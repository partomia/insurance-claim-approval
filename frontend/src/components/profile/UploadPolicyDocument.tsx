import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FileInput } from "@/components/ui/file-input";
import { apiFetch } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";
import { CheckCircle2, Sparkles } from "lucide-react";
import { formatINR } from "@/lib/currency";

interface PolicyFromDocumentResponse {
  policy_number: string;
  policy_type: string;
  coverage_limit: number;
  deductible: number;
  rag_chunks_indexed: number;
  rag_status: string;
  extracted_fields: Record<string, unknown>;
}

interface UploadPolicyDocumentProps {
  onCreated: () => void;
}

export function UploadPolicyDocument({ onCreated }: UploadPolicyDocumentProps) {
  const { error, success } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PolicyFromDocumentResponse | null>(null);

  const handleUpload = async () => {
    if (!file) {
      error("Choose a policy schedule PDF or image to upload.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await apiFetch("/api/policies/from-document", {
        method: "POST",
        body: fd,
      });
      if (res.ok) {
        const data: PolicyFromDocumentResponse = await res.json();
        setResult(data);
        success(`Policy ${data.policy_number} connected and indexed.`);
        setFile(null);
        onCreated();
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  if (result) {
    const clauseLabel =
      result.rag_status === "skipped_duplicate"
        ? "Schedule already indexed"
        : `${result.rag_chunks_indexed} clause${result.rag_chunks_indexed === 1 ? "" : "s"} indexed for AI search`;

    return (
      <Card className="ring-success-border bg-success-subtle">
        <CardContent className="pt-6 space-y-4">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-8 w-8 shrink-0 text-success" />
            <div className="space-y-1">
              <p className="font-semibold">Policy connected</p>
              <p className="text-sm text-muted-foreground">
                {result.policy_type} · {result.policy_number}
              </p>
              <p className="text-sm">
                Sum insured {formatINR(result.coverage_limit)} · Compulsory excess {formatINR(result.deductible)}
              </p>
              <p className="flex items-center gap-1.5 text-sm text-success">
                <Sparkles className="h-4 w-4" />
                {clauseLabel}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/claim">
              <Button size="sm">Start a claim</Button>
            </Link>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setResult(null);
                onCreated();
              }}
            >
              Upload another
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <FileInput
        accept=".pdf,.png,.jpg,.jpeg"
        placeholder="Upload policy schedule"
        onFilesSelected={(files) => setFile(files[0] ?? null)}
      />
      <Button type="button" onClick={handleUpload} disabled={loading || !file} className="w-full">
        {loading ? "Extracting & indexing..." : "Upload & connect policy"}
      </Button>
    </div>
  );
}
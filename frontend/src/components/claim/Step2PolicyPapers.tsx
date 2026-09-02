import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { PolicyContextPreview } from "./PolicyContextPreview";
import { FileInput } from "@/components/ui/file-input";
import { apiFetch, apiJson } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";
import { formatINR } from "@/lib/currency";

interface PolicySummary {
  id: number;
  policy_number: string;
  policy_type: string;
  coverage_limit: number;
  document_count: number;
  status: string;
}

interface PolicyDoc {
  id: number;
  title: string;
  section_ref: string;
  content_preview: string;
}

interface Step2Props {
  claimId: string;
  policyNumber: string;
  setPolicyNumber: (v: string) => void;
  policyContext: Record<string, unknown> | null;
  setPolicyContext: (ctx: Record<string, unknown>) => void;
  onContinue: () => void;
  onBack: () => void;
}

export function Step2PolicyPapers({
  claimId,
  policyNumber,
  setPolicyNumber,
  policyContext,
  setPolicyContext,
  onContinue,
  onBack,
}: Step2Props) {
  const { error, success } = useToast();
  const [tab, setTab] = useState<"fetch" | "upload">("fetch");
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [docs, setDocs] = useState<PolicyDoc[]>([]);
  const [loadingPolicies, setLoadingPolicies] = useState(true);
  const [loading, setLoading] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    apiJson<PolicySummary[]>("/api/policies/me")
      .then((data) => setPolicies(Array.isArray(data) ? data : []))
      .catch(console.error)
      .finally(() => setLoadingPolicies(false));
  }, []);

  useEffect(() => {
    if (!policyNumber) {
      setDocs([]);
      return;
    }
    apiJson<PolicyDoc[]>(`/api/policies/${policyNumber}/documents`)
      .then((data) => setDocs(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, [policyNumber]);

  const attachPolicy = async (selectedPolicyNumber: string) => {
    setAttaching(true);
    try {
      const res = await apiFetch(
        `/api/claims/${claimId}/draft`,
        {
          method: "PATCH",
          body: JSON.stringify({ policy_number: selectedPolicyNumber }),
        },
        { json: true }
      );
      if (res.ok) {
        setPolicyNumber(selectedPolicyNumber);
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setAttaching(false);
    }
  };

  const selectPolicy = async (selectedPolicyNumber: string) => {
    if (selectedPolicyNumber === policyNumber) return;
    await attachPolicy(selectedPolicyNumber);
  };

  const fetchAndAnalyze = async () => {
    if (!policyNumber) {
      error("Select a policy from your account first.");
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch(`/api/claims/${claimId}/policy-documents/fetch`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        setPolicyContext(data);
        if (data.policy_number) {
          setPolicyNumber(data.policy_number);
        }
        success("Policy documents analyzed.");
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  const uploadViaProfile = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const uploadRes = await apiFetch("/api/policies/from-document", {
        method: "POST",
        body: fd,
      });
      if (!uploadRes.ok) {
        const err = await uploadRes.json();
        error(formatApiError(err.detail));
        return;
      }
      const uploaded = await uploadRes.json();
      const selectedPolicyNumber = uploaded.policy_number as string;

      const attachRes = await apiFetch(
        `/api/claims/${claimId}/draft`,
        {
          method: "PATCH",
          body: JSON.stringify({ policy_number: selectedPolicyNumber }),
        },
        { json: true }
      );
      if (!attachRes.ok) {
        const err = await attachRes.json();
        error(formatApiError(err.detail));
        return;
      }
      setPolicyNumber(selectedPolicyNumber);

      const analyzeRes = await apiFetch(`/api/claims/${claimId}/policy-documents/fetch`, {
        method: "POST",
      });
      if (analyzeRes.ok) {
        const data = await analyzeRes.json();
        setPolicyContext(data);
        success(`Policy ${selectedPolicyNumber} uploaded and analyzed.`);
      } else {
        const err = await analyzeRes.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  const uploadAndAnalyze = async () => {
    await uploadViaProfile();
  };

  const hasContext = Boolean(policyContext?.coverage_summary || policyContext?.llm_analysis);
  const selectedPolicy = policies.find((p) => p.policy_number === policyNumber);
  const policiesWithDocs = policies.filter((p) => p.document_count > 0);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Step 2 — Motor Policy Papers</h2>
      <p className="text-sm text-muted-foreground">
        Choose a saved policy from your profile or upload a PDF. Groq AI will analyze coverage before you continue.
      </p>

      <div className="flex gap-2 border-b">
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            tab === "fetch" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setTab("fetch")}
        >
          Fetch from account
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            tab === "upload" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setTab("upload")}
        >
          Upload manually
        </button>
      </div>

      {tab === "fetch" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="p-4 border rounded-lg bg-card space-y-4">
            <h3 className="font-medium">Your saved motor policies</h3>
            {loadingPolicies ? (
              <p className="text-sm text-muted-foreground">Loading policies...</p>
            ) : policiesWithDocs.length === 0 ? (
              <div className="text-sm text-muted-foreground space-y-2">
                <p>No policies with uploaded schedules yet.</p>
                <Link to="/policies/connect" className="font-medium text-primary hover:underline">
                  Connect a policy →
                </Link>
              </div>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {policiesWithDocs.map((p) => (
                  <button
                    key={p.policy_number}
                    type="button"
                    disabled={attaching}
                    onClick={() => selectPolicy(p.policy_number)}
                    className={`w-full text-left p-3 border rounded-lg transition-colors ${
                      policyNumber === p.policy_number
                        ? "border-primary bg-primary/5"
                        : "hover:bg-muted/50"
                    }`}
                  >
                    <p className="text-sm font-medium">
                      {p.policy_type} — {p.policy_number}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatINR(p.coverage_limit)} · {p.document_count} document
                      {p.document_count === 1 ? "" : "s"}
                    </p>
                  </button>
                ))}
              </div>
            )}

            {selectedPolicy && (
              <div>
                <h4 className="text-sm font-medium mb-2">Schedule sections</h4>
                {docs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No schedule uploaded for this policy.{" "}
                    <Link to="/policies/connect" className="text-primary hover:underline">
                      Upload on Connect Policy
                    </Link>
                  </p>
                ) : (
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {docs.map((d) => (
                      <div key={d.id} className="p-2 border rounded text-sm">
                        <p className="font-medium">{d.title}</p>
                        <p className="text-xs text-muted-foreground">{d.section_ref}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <Button
              className="w-full"
              onClick={fetchAndAnalyze}
              disabled={loading || !policyNumber || docs.length === 0}
            >
              {loading ? "Analyzing with Groq..." : "Load & Analyze"}
            </Button>
          </div>
          <div className="p-4 border rounded-lg bg-muted/30">
            <h3 className="font-medium mb-2">Preview</h3>
            {hasContext ? (
              <PolicyContextPreview context={policyContext as never} />
            ) : (
              <p className="text-sm text-muted-foreground">Analysis will appear here after loading policy papers.</p>
            )}
          </div>
        </div>
      )}

      {tab === "upload" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="p-4 border rounded-lg bg-card space-y-4">
            <h3 className="font-medium">Upload motor policy schedule</h3>
            <FileInput
              accept=".pdf,.png,.jpg,.jpeg"
              placeholder="Upload policy schedule PDF or image"
              onFilesSelected={(files) => setFile(files[0] ?? null)}
            />
            <Button className="w-full" onClick={uploadAndAnalyze} disabled={loading || !file}>
              {loading ? "Analyzing with Groq..." : "Upload & Analyze"}
            </Button>
          </div>
          <div className="p-4 border rounded-lg bg-muted/30">
            <h3 className="font-medium mb-2">Preview</h3>
            {hasContext ? (
              <PolicyContextPreview context={policyContext as never} />
            ) : (
              <p className="text-sm text-muted-foreground">Upload a policy document to see Groq analysis.</p>
            )}
          </div>
        </div>
      )}

      <div className="flex justify-between gap-3 border-t pt-4">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <Button onClick={onContinue} disabled={!hasContext}>
          Continue →
        </Button>
      </div>
    </div>
  );
}
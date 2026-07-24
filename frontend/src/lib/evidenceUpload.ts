import { apiFetch } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface EvidenceReplaceResponse {
  message: string;
  document_id: number;
  pipeline_run_id: number;
}

export interface EvidenceAcknowledgeResponse {
  message: string;
  evidence_mismatch: boolean;
  pipeline_run_id: number;
}

export async function replaceEvidenceDocument(
  claimId: string,
  file: File,
  documentId: number
): Promise<EvidenceReplaceResponse> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("document_id", String(documentId));

  const res = await apiFetch(
    `/api/claims/${claimId}/evidence/replace`,
    {
      method: "POST",
      headers: authHeaders(),
      body: fd,
    },
    { redirectOn401: true }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to replace document");
  }

  return res.json();
}

export async function acknowledgeEvidenceDocument(
  claimId: string,
  documentId: number,
  note?: string
): Promise<EvidenceAcknowledgeResponse> {
  const res = await apiFetch(
    `/api/claims/${claimId}/evidence/${documentId}/acknowledge`,
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ note: note || null }),
    },
    { redirectOn401: true, json: true }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to acknowledge document");
  }

  return res.json();
}

import { apiFetch } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export async function uploadClaimDocument(
  claimId: string,
  docType: string,
  files: File[]
): Promise<{ message: string }> {
  const fd = new FormData();
  fd.append("doc_type", docType);
  files.forEach((file) => fd.append("files", file));

  const res = await apiFetch(
    `/api/claims/${claimId}/documents`,
    {
      method: "POST",
      headers: authHeaders(),
      body: fd,
    },
    { redirectOn401: true }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to upload document");
  }

  return res.json();
}

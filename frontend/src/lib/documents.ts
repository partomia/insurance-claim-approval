import { apiFetch } from "@/lib/api";

function documentUrl(claimId: string | number, documentId: number, download = false): string {
  const params = download ? "?download=1" : "";
  return `/api/claims/${claimId}/documents/${documentId}/file${params}`;
}

export async function openClaimDocument(
  claimId: string | number,
  documentId: number,
  _filename?: string
): Promise<void> {
  const res = await apiFetch(documentUrl(claimId, documentId));
  if (!res.ok) {
    throw new Error("Could not open document");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (!opened) {
    URL.revokeObjectURL(url);
    throw new Error("Pop-up blocked. Allow pop-ups to view documents.");
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function downloadClaimDocument(
  claimId: string | number,
  documentId: number,
  filename: string
): Promise<void> {
  const res = await apiFetch(documentUrl(claimId, documentId, true));
  if (!res.ok) {
    throw new Error("Could not download document");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

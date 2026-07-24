import { insurerApiFetch } from "@/lib/insurerApi";

function documentUrl(claimId: string | number, documentId: number, download = false): string {
  const params = download ? "?download=1" : "";
  return `/api/insurer/claims/${claimId}/documents/${documentId}/file${params}`;
}

export async function openInsurerClaimDocument(
  claimId: string | number,
  documentId: number
): Promise<void> {
  const res = await insurerApiFetch(documentUrl(claimId, documentId));
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

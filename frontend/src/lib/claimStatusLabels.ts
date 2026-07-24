/** Customer-facing claim status labels for filters and summaries. */

export const CLAIM_STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  PROCESSING: "Processing",
  ANALYSIS_COMPLETE: "Analysis complete",
  PENDING_REVIEW: "Expert review",
  HUMAN_REVIEW: "Expert review",
  REQUEST_MORE_INFO: "Action needed",
  SUBMISSION_READY: "Ready to submit",
  SUBMITTED_TO_INSURER: "Submitted to insurer",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

export function claimStatusLabel(status: string): string {
  return CLAIM_STATUS_LABELS[status.toUpperCase()] ?? status.replace(/_/g, " ");
}

export function riskLevelLabel(score: number): string {
  const pct = score * 100;
  if (pct < 30) return "Low";
  if (pct < 50) return "Moderate";
  return "Higher";
}

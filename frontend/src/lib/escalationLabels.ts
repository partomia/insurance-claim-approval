/** Plain-language labels for internal escalation flag codes. */

export const ESCALATION_FLAG_LABELS: Record<string, string> = {
  high_fraud_score: "Higher fraud risk — needs extra review",
  low_evidence_confidence: "Documents are unclear or incomplete",
  early_claim_high_amount: "Large claim filed soon after the policy started",
  clause_mismatch: "Policy coverage may not match this incident",
  evidence_mismatch: "An uploaded document may not be the right type",
  extraction_failed: "We could not read one of the uploaded files",
  missing_documents: "Some required documents are still missing",
};

export function friendlyEscalationFlag(flag: string): string {
  if (ESCALATION_FLAG_LABELS[flag]) {
    return ESCALATION_FLAG_LABELS[flag];
  }
  return flag
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Prefer friendly flag labels over stored technical API messages. */
export function formatEscalationList(
  messages?: string[] | null,
  flags?: string[] | null
): string[] {
  const cleanFlags = (flags ?? []).filter(Boolean);
  if (cleanFlags.length > 0) {
    return cleanFlags.map(friendlyEscalationFlag);
  }

  return (messages ?? []).map((m) => m.trim()).filter(Boolean);
}

/** Join escalation items into a single summary line. */
export function formatEscalationSummary(
  messages?: string[] | null,
  flags?: string[] | null
): string {
  return formatEscalationList(messages, flags).join(" · ");
}

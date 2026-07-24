export interface DocumentTypeOption {
  value: string;
  label: string;
}

export const EXPERT_DOCUMENT_TYPES: DocumentTypeOption[] = [
  { value: "MEDICAL", label: "Medical bill / discharge summary" },
  { value: "INVOICE", label: "Invoice / itemized bill" },
  { value: "POLICE_REPORT", label: "Police / FIR report" },
  { value: "PROOF", label: "Supporting proof document" },
  { value: "GOV_ID", label: "Government ID" },
  { value: "POLICY_PAPER", label: "Policy document" },
  { value: "OTHER", label: "Other document" },
];

export function documentTypeLabel(value: string): string {
  return EXPERT_DOCUMENT_TYPES.find((d) => d.value === value)?.label ?? value.replace(/_/g, " ");
}

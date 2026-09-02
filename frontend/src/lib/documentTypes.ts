export interface DocumentTypeOption {
  value: string;
  label: string;
}

/** Motor-vehicle claim document types shown in expert / customer UIs. */
export const EXPERT_DOCUMENT_TYPES: DocumentTypeOption[] = [
  { value: "DAMAGE_PHOTO", label: "Damage photo" },
  { value: "REPAIR_ESTIMATE", label: "Repair estimate / garage invoice" },
  { value: "POLICE_REPORT", label: "Police / FIR report" },
  { value: "DRIVER_LICENSE", label: "Driver's licence" },
  { value: "VEHICLE_REGISTRATION", label: "Vehicle registration (RC)" },
  { value: "TOWING_INVOICE", label: "Towing invoice" },
  { value: "THIRD_PARTY_STATEMENT", label: "Third-party statement" },
  { value: "POLICY_PAPER", label: "Policy document" },
  { value: "OTHER", label: "Other document" },
];

export function documentTypeLabel(value: string): string {
  return EXPERT_DOCUMENT_TYPES.find((d) => d.value === value)?.label ?? value.replace(/_/g, " ");
}

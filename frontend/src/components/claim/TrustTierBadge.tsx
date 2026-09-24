/**
 * Customer Trust Score tier (backend/services/customer_trust_service.py).
 * Shared by the Claim Insights trust card and the Book of Business table.
 */
const TIER_CONFIG: Record<string, { label: string; className: string }> = {
  PREFERRED: {
    label: "Preferred",
    className: "bg-success text-success-foreground border-success",
  },
  STANDARD: {
    label: "Standard",
    className: "bg-muted text-foreground border-border",
  },
  WATCH: {
    label: "Watch",
    className: "bg-warning text-warning-foreground border-warning",
  },
  UNSCORED: {
    label: "Unscored",
    className: "bg-transparent text-muted-foreground border-dashed border-border",
  },
};

export function TrustTierBadge({ tier }: { tier: string }) {
  const t = tier.toUpperCase();
  const config = TIER_CONFIG[t] ?? { label: tier, className: "bg-muted text-foreground border-border" };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${config.className}`}
    >
      {config.label}
    </span>
  );
}

/**
 * Shared risk-band badge for the datalakehouse fraud risk signal
 * (PolicyRiskSignal.claim_risk_band — LOW/MEDIUM/HIGH), computed by the CDE
 * claims-analytics pipeline (see cde/README.md) and ingested via
 * scripts/ingest_lakehouse.py.
 *
 * Deliberately reused in both:
 *   - Insurer Book of Business page (browse/filter all lakehouse policies)
 *   - Claim Insights panel (a single claim's policy risk signal, if any)
 * so the same risk band always looks identical wherever it appears.
 */
const BAND_CONFIG: Record<string, { label: string; className: string }> = {
  LOW: {
    label: "Low risk",
    className: "bg-success text-success-foreground border-success",
  },
  MEDIUM: {
    label: "Medium risk",
    className: "bg-warning text-warning-foreground border-warning",
  },
  HIGH: {
    label: "High risk",
    className: "bg-destructive text-white border-destructive",
  },
};

export function RiskBandBadge({ band }: { band: string }) {
  const b = band.toUpperCase();
  const config = BAND_CONFIG[b] ?? {
    label: band,
    className: "bg-muted text-foreground border-border",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${config.className}`}
    >
      {config.label}
    </span>
  );
}

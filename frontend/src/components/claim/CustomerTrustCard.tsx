import { TrustTierBadge } from "./TrustTierBadge";
import { MinusCircle, PlusCircle, ShieldCheck, Circle } from "lucide-react";

export interface CustomerTrustReason {
  code: string;
  label: string;
  impact: "positive" | "negative" | "neutral" | string;
}

export interface CustomerTrust {
  score?: number | null;
  tier: string;
  reasons?: CustomerTrustReason[];
  credit_score?: number | null;
  credit_band?: string | null;
  driving_record_band?: string | null;
  source?: string | null;
  as_of?: string | null;
  at_decision?: boolean;
}

const TIER_EFFECT: Record<string, string> = {
  PREFERRED: "Higher auto-approval amount limit",
  STANDARD: "Standard auto-approval amount limit",
  WATCH: "Lower auto-approval amount limit — larger claims go to manual review",
  UNSCORED: "No profile data — standard rules apply",
};

function ReasonIcon({ impact }: { impact: string }) {
  if (impact === "positive") return <PlusCircle className="h-3.5 w-3.5 shrink-0 text-success" />;
  if (impact === "negative") return <MinusCircle className="h-3.5 w-3.5 shrink-0 text-warning" />;
  return <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}

export function CustomerTrustCard({ trust }: { trust: CustomerTrust }) {
  const reasons = trust.reasons ?? [];
  const sourceLabel =
    trust.source === "GOLD_PIPELINE" ? "CDE customer-profile pipeline" : trust.source === "DEMO_SEED" ? "demo seed data" : trust.source;

  return (
    <div className="p-4 bg-card border rounded-lg shadow-sm space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" />
          Customer Trust Score
        </p>
        <TrustTierBadge tier={trust.tier} />
      </div>

      {trust.score != null && (
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-muted-foreground text-xs">Trust score</p>
            <p className="font-semibold">{trust.score} / 100</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Credit</p>
            <p className="font-semibold">
              {trust.credit_score ?? "No hit"}
              {trust.credit_band && trust.credit_band !== "NO_HIT" && (
                <span className="ml-1 text-xs font-normal text-muted-foreground">{trust.credit_band.toLowerCase()}</span>
              )}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Driving record</p>
            <p className="font-semibold">{trust.driving_record_band ? trust.driving_record_band.toLowerCase() : "—"}</p>
          </div>
        </div>
      )}

      {reasons.length > 0 && (
        <ul className="space-y-1">
          {reasons.slice(0, 6).map((r) => (
            <li key={r.code} className="flex items-center gap-1.5 text-xs">
              <ReasonIcon impact={r.impact} />
              {r.label}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs font-medium">{TIER_EFFECT[trust.tier] ?? ""}</p>
      <p className="text-[11px] text-muted-foreground">
        {trust.at_decision ? "Value used when this claim was decided" : "Current value (claim not yet decided)"}
        {sourceLabel ? ` · from ${sourceLabel}` : ""}. Affects only how fast a claim can be auto-approved — never
        whether a covered claim is paid.
      </p>
    </div>
  );
}

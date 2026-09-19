import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { RiskBandBadge } from "@/components/claim/RiskBandBadge";
import { insurerApiJson } from "@/lib/insurerApi";
import { formatINR } from "@/lib/currency";
import { AlertTriangle, Database, ShieldAlert, TrendingUp } from "lucide-react";

interface PolicyRiskSignal {
  total_claims_count: number;
  claims_count_12m: number;
  total_claimed_amount: number;
  avg_claim_amount: number;
  amount_vs_segment_avg_pct?: number | null;
  claim_frequency_percentile?: number | null;
  linked_high_risk_garage: boolean;
  fraud_risk_score: number;
  claim_risk_band: string;
  source: string;
  ingested_at: string;
}

interface BookOfBusinessPolicy {
  policy_id: number;
  policy_number: string;
  customer_name: string;
  customer_email: string;
  provider_name?: string | null;
  policy_type: string;
  status: string;
  coverage_limit: number;
  premium_amount: number;
  covered_make?: string | null;
  covered_model?: string | null;
  risk?: PolicyRiskSignal | null;
}

interface BookOfBusinessStats {
  total_policies: number;
  low_count: number;
  medium_count: number;
  high_count: number;
  high_risk_garage_linked_count: number;
  avg_fraud_risk_score: number;
}

const RISK_BAND_OPTIONS = ["", "LOW", "MEDIUM", "HIGH"];
const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "score_desc", label: "Fraud score (high → low)" },
  { value: "score_asc", label: "Fraud score (low → high)" },
  { value: "claims_desc", label: "Total claims (most first)" },
];

export function InsurerBookOfBusiness() {
  const [stats, setStats] = useState<BookOfBusinessStats | null>(null);
  const [policies, setPolicies] = useState<BookOfBusinessPolicy[]>([]);
  const [riskBand, setRiskBand] = useState("");
  const [highRiskGarageOnly, setHighRiskGarageOnly] = useState(false);
  const [sort, setSort] = useState("score_desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    insurerApiJson<BookOfBusinessStats>("/api/insurer/book-of-business/stats")
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ sort });
        if (riskBand) params.set("risk_band", riskBand);
        if (highRiskGarageOnly) params.set("high_risk_garage_only", "true");
        const data = await insurerApiJson<BookOfBusinessPolicy[]>(
          `/api/insurer/book-of-business?${params.toString()}`
        );
        setPolicies(Array.isArray(data) ? data : []);
        setError(null);
      } catch {
        setError("Could not load Book of Business.");
        setPolicies([]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [riskBand, highRiskGarageOnly, sort]);

  const cards = stats
    ? [
        {
          label: "Lakehouse policies",
          value: stats.total_policies,
          icon: <Database className="h-5 w-5" />,
          hint: "Ingested from the CDE claims-analytics pipeline",
        },
        {
          label: "High risk",
          value: stats.high_count,
          icon: <ShieldAlert className="h-5 w-5" />,
          hint: `${stats.medium_count} medium · ${stats.low_count} low`,
          tone: stats.high_count > 0 ? ("danger" as const) : ("default" as const),
        },
        {
          label: "Linked to a flagged garage",
          value: stats.high_risk_garage_linked_count,
          icon: <AlertTriangle className="h-5 w-5" />,
          hint: "Policy has ≥1 claim at a high-risk garage",
          tone: stats.high_risk_garage_linked_count > 0 ? ("warning" as const) : ("default" as const),
        },
        {
          label: "Avg. fraud risk score",
          value: stats.avg_fraud_risk_score.toFixed(1),
          icon: <TrendingUp className="h-5 w-5" />,
          hint: "Across all ingested policies (0–100)",
        },
      ]
    : [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Book of Business"
        description="Policies and fraud risk signals computed by the CDE claims-analytics pipeline (Iceberg lakehouse) — see cde/README.md."
      />

      {stats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {cards.map((c) => (
            <StatCard key={c.label} label={c.label} value={c.value} hint={c.hint} icon={c.icon} tone={c.tone} />
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Policies</CardTitle>
              <CardDescription>
                Only policies ingested from the lakehouse (policy numbers starting <code>LH-POL-</code>) appear here.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                className="w-full sm:w-44"
                value={riskBand}
                onChange={(e) => setRiskBand(e.target.value)}
                aria-label="Filter by risk band"
              >
                {RISK_BAND_OPTIONS.map((b) => (
                  <option key={b || "all"} value={b}>
                    {b ? `${b.charAt(0)}${b.slice(1).toLowerCase()} risk` : "All risk bands"}
                  </option>
                ))}
              </Select>
              <Select
                className="w-full sm:w-56"
                value={sort}
                onChange={(e) => setSort(e.target.value)}
                aria-label="Sort policies"
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
              <label className="flex items-center gap-2 text-sm whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={highRiskGarageOnly}
                  onChange={(e) => setHighRiskGarageOnly(e.target.checked)}
                  className="h-4 w-4 rounded border-input"
                />
                Flagged garage only
              </label>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((k) => (
                <Skeleton key={k} className="h-12" />
              ))}
            </div>
          ) : error ? (
            <p className="py-8 text-center text-sm text-destructive">{error}</p>
          ) : policies.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No policies match this filter — try clearing it, or run{" "}
              <code>bash cml/cli.sh lakehouse ingest</code> if nothing has been ingested yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Policy</th>
                    <th className="py-2 pr-3 font-medium">Customer</th>
                    <th className="py-2 pr-3 font-medium">Provider</th>
                    <th className="py-2 pr-3 font-medium">Coverage</th>
                    <th className="py-2 pr-3 font-medium">Risk band</th>
                    <th className="py-2 pr-3 font-medium">Fraud score</th>
                    <th className="py-2 pr-3 font-medium">Claims (12m / total)</th>
                    <th className="py-2 font-medium">Flagged garage</th>
                  </tr>
                </thead>
                <tbody>
                  {policies.map((p) => (
                    <tr key={p.policy_id} className="border-b last:border-0 hover:bg-muted/40">
                      <td className="py-3 pr-3">
                        <div className="font-medium">{p.policy_number}</div>
                        <div className="text-xs text-muted-foreground">
                          {p.covered_make} {p.covered_model}
                        </div>
                      </td>
                      <td className="py-3 pr-3">
                        <div>{p.customer_name}</div>
                        <div className="text-xs text-muted-foreground">{p.customer_email}</div>
                      </td>
                      <td className="py-3 pr-3">{p.provider_name ?? "—"}</td>
                      <td className="py-3 pr-3">{formatINR(p.coverage_limit)}</td>
                      <td className="py-3 pr-3">
                        {p.risk ? <RiskBandBadge band={p.risk.claim_risk_band} /> : "—"}
                      </td>
                      <td className="py-3 pr-3 font-medium">
                        {p.risk ? p.risk.fraud_risk_score.toFixed(1) : "—"}
                      </td>
                      <td className="py-3 pr-3 text-muted-foreground">
                        {p.risk ? `${p.risk.claims_count_12m} / ${p.risk.total_claims_count}` : "—"}
                      </td>
                      <td className="py-3">
                        {p.risk?.linked_high_risk_garage ? (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-warning">
                            <AlertTriangle className="h-3.5 w-3.5" /> Yes
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">No</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

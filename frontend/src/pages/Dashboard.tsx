import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimAnalysisPanel, type AIAnalysis } from "@/components/claim/ClaimAnalysisPanel";
import { apiJson } from "@/lib/api";
import { formatINR } from "@/lib/currency";
import {
  ArrowRight,
  Bell,
  BadgeCheck,
  ClipboardList,
  Clock3,
  FilePlus2,
  Shield,
  Sparkles,
} from "lucide-react";

interface PolicySummary {
  id: number;
  policy_number: string;
  policy_type: string;
  provider_name?: string | null;
  coverage_limit: number;
  coverage_remaining?: number | null;
  expiry_date: string;
  premium_amount?: number | null;
}

interface DashboardStats {
  kyc_complete: boolean;
  kyc_status?: string;
  active_policies: number;
  total_claims: number;
  pending_claims: number;
  connected_policies: PolicySummary[];
  recent_analyses: (AIAnalysis & { claim_id: string; claim_db_id: number; status: string })[];
  notifications: { type: string; message: string }[];
  recommended_actions: string[];
  recent_activity: {
    id: number;
    claim_id: string;
    status: string;
    claim_amount: number;
    incident_description: string;
    created_at: string;
  }[];
}

export function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiJson<DashboardStats>("/api/dashboard/stats")
      .then(setStats)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-8">
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((k) => (
            <Skeleton key={k} className="h-28" />
          ))}
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          <Skeleton className="h-72 lg:col-span-2" />
          <div className="space-y-6">
            <Skeleton className="h-40" />
            <Skeleton className="h-40" />
          </div>
        </div>
      </div>
    );
  }
  if (!stats) return <p className="text-destructive">Could not load dashboard.</p>;

  const kycLabel = stats.kyc_status?.toLowerCase() ?? "pending";
  const kycTone = stats.kyc_complete ? "success" : "warning";

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Motor Insurance Claim Assistant"
        title="Your Motor Claim Workspace"
        description="Know if your claim is likely to be approved before you submit to your insurer."
        actions={
          <>
            {!stats.kyc_complete && (
              <Link to="/kyc">
                <Button variant="outline">Complete KYC</Button>
              </Link>
            )}
            <Link to="/claim">
              <Button>
                <FilePlus2 className="h-4 w-4" />
                File Motor Claim
              </Button>
            </Link>
          </>
        }
      />

      {!stats.kyc_complete && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning-border bg-warning-subtle p-4">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-warning/20 text-warning">
              <Shield className="h-4 w-4" />
            </span>
            <div>
              <p className="font-medium">Complete one-time KYC</p>
              <p className="text-sm text-muted-foreground">Verify identity once to connect motor policies and file claims.</p>
            </div>
          </div>
          <Link to="/kyc">
            <Button size="sm">
              Start KYC <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </Link>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Connected Motor Policies"
          value={stats.active_policies}
          icon={<Shield className="h-5 w-5" />}
        />
        <StatCard
          label="Motor Claims Filed"
          value={stats.total_claims}
          icon={<ClipboardList className="h-5 w-5" />}
        />
        <StatCard
          label="Claims In Progress"
          value={stats.pending_claims}
          icon={<Clock3 className="h-5 w-5" />}
        />
        <StatCard
          label="KYC Status"
          value={<span className="capitalize text-xl sm:text-2xl">{kycLabel}</span>}
          tone={kycTone}
          icon={<BadgeCheck className="h-5 w-5" />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <section>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <Sparkles className="h-5 w-5" /> Recent AI Analyses
              </h2>
            </div>
            {stats.recent_analyses.length > 0 ? (
              <div className="space-y-4">
                {stats.recent_analyses.slice(0, 2).map((a) => (
                  <div key={a.claim_id} className="rounded-xl border bg-card p-4">
                    <div className="flex items-center justify-between mb-3">
                      <Link to={`/analysis/${a.claim_db_id}`} className="font-medium hover:underline">{a.claim_id}</Link>
                      <span className="text-xs text-muted-foreground">{a.status.replaceAll("_", " ")}</span>
                    </div>
                    <ClaimAnalysisPanel analysis={a} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed p-8 text-center text-muted-foreground">
                No motor claim analyses yet. File a claim to get AI-powered approval predictions.
              </div>
            )}
          </section>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2"><Shield className="h-4 w-4" /> Connected Motor Policies</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {stats.connected_policies.length === 0 ? (
                <div className="rounded-lg border border-dashed p-4 text-sm">
                  <p className="text-muted-foreground">No policies connected.</p>
                  <Link to="/policies/connect" className="text-primary hover:underline">Connect policy</Link>
                </div>
              ) : (
                stats.connected_policies.slice(0, 4).map((p) => (
                  <div key={p.id} className="rounded-lg bg-muted/40 p-3 text-sm">
                    <p className="font-medium">{p.provider_name ?? "Insurance"} · {p.policy_type}</p>
                    <p className="text-muted-foreground">{p.policy_number}</p>
                    <p className="mt-1">Coverage remaining: {formatINR(p.coverage_remaining ?? p.coverage_limit)}</p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          {(stats.notifications.length > 0 || stats.recommended_actions.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2"><Bell className="h-4 w-4" /> Recommended Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {stats.recommended_actions.map((a) => (
                  <p key={a} className="text-muted-foreground">• {a}</p>
                ))}
                {stats.notifications.map((n, i) => (
                  <p key={i} className="text-muted-foreground">• {n.message}</p>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader><CardTitle className="text-base">Recent Motor Claims</CardTitle></CardHeader>
            <CardContent className="space-y-1">
              {stats.recent_activity.length === 0 ? (
                <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  No recent claims.
                </p>
              ) : (
                stats.recent_activity.slice(0, 5).map((c) => (
                  <Link
                    key={c.id}
                    to={`/analysis/${c.id}`}
                    className="-mx-2 block rounded-lg p-2 text-sm transition-colors hover:bg-muted/60"
                  >
                    <p className="font-medium">{c.claim_id}</p>
                    <p className="truncate text-muted-foreground">{c.incident_description}</p>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
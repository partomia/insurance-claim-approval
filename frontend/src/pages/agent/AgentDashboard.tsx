import type React from "react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusDonutChart } from "@/components/dashboard/ClaimStatusDonutChart";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { agentApiJson } from "@/lib/agentApi";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { useChartColors } from "@/lib/chartTheme";
import { AlertTriangle, CheckCircle2, ClipboardList, Clock3, ShieldAlert } from "lucide-react";
import { formatINR } from "@/lib/currency";

interface AgentStats {
  assigned_total: number;
  pending_review: number;
  submission_ready: number;
  needs_improvement: number;
  avg_approval_probability: number;
  claims_by_status: { status: string; label: string; count: number }[];
  claims_by_customer: { customer_id: number; customer_name: string; count: number }[];
}

interface QueueClaim {
  id: number;
  claim_id: string;
  status: string;
  claim_amount: number;
  customer_name: string;
  customer_email: string;
  approval_probability?: number | null;
  fraud_score?: number | null;
  document_count?: number;
  has_document_issues?: boolean;
  assigned_at?: string | null;
}

const URGENCY_ORDER: Record<string, number> = {
  PENDING_REVIEW: 0,
  HUMAN_REVIEW: 1,
  ANALYSIS_COMPLETE: 2,
  REQUEST_MORE_INFO: 3,
  SUBMISSION_READY: 4,
};

function sortByUrgency(claims: QueueClaim[]) {
  return [...claims].sort((a, b) => {
    const ua = URGENCY_ORDER[a.status] ?? 99;
    const ub = URGENCY_ORDER[b.status] ?? 99;
    if (ua !== ub) return ua - ub;
    return (b.approval_probability ?? 0) - (a.approval_probability ?? 0);
  });
}

export function AgentDashboard() {
  const navigate = useNavigate();
  const colors = useChartColors();
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [queue, setQueue] = useState<QueueClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [statsData, claimsData] = await Promise.all([
          agentApiJson<AgentStats>("/api/agent/dashboard/stats"),
          agentApiJson<QueueClaim[]>("/api/agent/claims"),
        ]);
        setStats(statsData);
        setQueue(sortByUrgency(claimsData));
        setError(null);
      } catch {
        setError("Could not load agent dashboard.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="space-y-8">
        <div className="space-y-2">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((k) => (
            <Skeleton key={k} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (error || !stats) {
    return <p className="text-destructive">{error ?? "Dashboard unavailable."}</p>;
  }

  const cards: Array<{
    label: string;
    value: React.ReactNode;
    icon: React.ReactNode;
    hint: string;
    tone?: "default" | "warning" | "success";
  }> = [
    { label: "Assigned claims in queue", value: stats.assigned_total, icon: <ClipboardList className="h-5 w-5" />, hint: "In your queue" },
    { label: "Expert Review", value: stats.pending_review, icon: <Clock3 className="h-5 w-5" />, hint: "Awaiting consultation" },
    { label: "Submission Ready", value: stats.submission_ready, icon: <CheckCircle2 className="h-5 w-5" />, hint: "Ready for insurer", tone: "success" },
    { label: "Needs Improvement", value: stats.needs_improvement, icon: <AlertTriangle className="h-5 w-5" />, hint: "Awaiting customer docs", tone: stats.needs_improvement > 0 ? "warning" : "default" },
    { label: "Avg Approval Probability", value: `${(stats.avg_approval_probability * 100).toFixed(0)}%`, icon: <ShieldAlert className="h-5 w-5" />, hint: "AI prediction across queue" },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Motor Claims Expert Workspace"
        description="Review assigned claims, documents, and policy requirements."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map((c) => (
          <StatCard
            key={c.label}
            label={c.label}
            value={c.value}
            hint={c.hint}
            icon={c.icon}
            tone={c.tone}
          />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Motor Claims Work Queue</CardTitle>
          <CardDescription>Assigned claims ready for expert review — click a row to open the workstation</CardDescription>
        </CardHeader>
        <CardContent>
          {queue.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">No assigned claims yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Claim ID</th>
                    <th className="py-2 pr-3 font-medium">Customer</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Claim amount</th>
                    <th className="py-2 pr-3 font-medium">Approval</th>
                    <th className="py-2 pr-3 font-medium">Fraud</th>
                    <th className="py-2 pr-3 font-medium">Docs</th>
                    <th className="py-2 pr-3 font-medium">Assigned</th>
                    <th className="py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((claim) => (
                    <tr
                      key={claim.id}
                      className="border-b last:border-0 hover:bg-muted/40 cursor-pointer"
                      onClick={() => navigate(`/agent/claims/${claim.id}`)}
                    >
                      <td className="py-3 pr-3 font-medium">{claim.claim_id}</td>
                      <td className="py-3 pr-3">
                        <div>{claim.customer_name}</div>
                        <div className="text-xs text-muted-foreground">{claim.customer_email}</div>
                      </td>
                      <td className="py-3 pr-3">
                        <ClaimStatusBadge status={claim.status} />
                      </td>
                      <td className="py-3 pr-3">{formatINR(claim.claim_amount)}</td>
                      <td className="py-3 pr-3">
                        {claim.approval_probability != null ? (
                          <span className="inline-flex rounded-full bg-success-subtle text-success px-2 py-0.5 text-xs font-semibold">
                            {(claim.approval_probability * 100).toFixed(0)}%
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-3 pr-3">
                        {claim.fraud_score != null ? `${(claim.fraud_score * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="py-3 pr-3">
                        {claim.document_count ?? 0}
                        {claim.has_document_issues && (
                          <AlertTriangle className="inline h-3.5 w-3.5 ml-1 text-warning" aria-label="Document issues" />
                        )}
                      </td>
                      <td className="py-3 pr-3 text-xs text-muted-foreground">
                        {claim.assigned_at ? new Date(claim.assigned_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="py-3">
                        <Button
                          type="button"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/agent/claims/${claim.id}`);
                          }}
                        >
                          Review
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Motor Claims by Status</CardTitle>
            <CardDescription>Click a slice to filter the claims queue</CardDescription>
          </CardHeader>
          <CardContent>
            <ClaimStatusDonutChart
              data={stats.claims_by_status}
              onStatusClick={(status) => navigate(`/agent/claims?status=${encodeURIComponent(status)}`)}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Motor Claims by Customer</CardTitle>
            <CardDescription>Volume per customer in your queue</CardDescription>
          </CardHeader>
          <CardContent>
            {stats.claims_by_customer.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">No assigned claims yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={stats.claims_by_customer}>
                  <XAxis dataKey="customer_name" tick={{ fill: colors.muted, fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fill: colors.muted, fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      background: colors.foreground === "#111827" ? "#fff" : "#1f2937",
                      border: `1px solid ${colors.border}`,
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" fill={colors.chart1} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div>
        <Link to="/agent/claims" className="text-primary hover:underline text-sm font-medium">
          View full claims queue →
        </Link>
      </div>
    </div>
  );
}
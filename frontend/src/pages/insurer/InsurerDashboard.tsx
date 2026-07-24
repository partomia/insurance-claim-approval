import type React from "react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { insurerApiJson } from "@/lib/insurerApi";
import { Building2, CheckCircle2, Clock3, DollarSign, XCircle } from "lucide-react";

interface InsurerStats {
  pending_decision: number;
  approved_total: number;
  rejected_total: number;
  total_approved_payout: number;
  recent_submissions: InsurerQueueClaim[];
}

interface InsurerQueueClaim {
  id: number;
  claim_id: string;
  status: string;
  claim_amount: number;
  customer_name: string;
  customer_email: string;
  policy_type?: string | null;
  assigned_agent?: string | null;
  updated_at: string;
  approval_probability?: number | null;
}

export function InsurerDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<InsurerStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    insurerApiJson<InsurerStats>("/api/insurer/dashboard/stats")
      .then(setStats)
      .catch(() => setError("Could not load insurer dashboard."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-8">
        <div className="space-y-2">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((k) => (
            <Skeleton key={k} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }
  if (error || !stats) return <p className="text-destructive">{error ?? "Dashboard unavailable."}</p>;

  const cards: Array<{
    label: string;
    value: React.ReactNode;
    icon: React.ReactNode;
    hint: string;
    tone?: "default" | "success" | "warning" | "danger";
  }> = [
    { label: "Pending decisions", value: stats.pending_decision, icon: <Clock3 className="h-5 w-5" />, hint: "Awaiting your review", tone: stats.pending_decision > 0 ? "warning" : "default" },
    { label: "Approved", value: stats.approved_total, icon: <CheckCircle2 className="h-5 w-5" />, hint: "Claims you approved", tone: "success" },
    { label: "Rejected", value: stats.rejected_total, icon: <XCircle className="h-5 w-5" />, hint: "Claims you rejected", tone: stats.rejected_total > 0 ? "danger" : "default" },
    {
      label: "Total approved payout",
      value: `$${stats.total_approved_payout.toLocaleString()}`,
      icon: <DollarSign className="h-5 w-5" />,
      hint: "Sum of approved payable amounts",
    },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Insurer Dashboard"
        description="Review claims submitted by ClaimCopilot experts and record final decisions."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Submission Queue
          </CardTitle>
          <CardDescription>Claims submitted to your company — open a row to review and decide</CardDescription>
        </CardHeader>
        <CardContent>
          {stats.recent_submissions.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">No pending submissions right now.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Claim ID</th>
                    <th className="py-2 pr-3 font-medium">Customer</th>
                    <th className="py-2 pr-3 font-medium">Expert</th>
                    <th className="py-2 pr-3 font-medium">Amount</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Updated</th>
                    <th className="py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_submissions.map((claim) => (
                    <tr
                      key={claim.id}
                      className="border-b last:border-0 hover:bg-muted/40 cursor-pointer"
                      onClick={() => navigate(`/insurer/claims/${claim.id}`)}
                    >
                      <td className="py-3 pr-3 font-medium">{claim.claim_id}</td>
                      <td className="py-3 pr-3">
                        <div>{claim.customer_name}</div>
                        <div className="text-xs text-muted-foreground">{claim.customer_email}</div>
                      </td>
                      <td className="py-3 pr-3">{claim.assigned_agent ?? "—"}</td>
                      <td className="py-3 pr-3">${claim.claim_amount.toLocaleString()}</td>
                      <td className="py-3 pr-3">
                        <ClaimStatusBadge status={claim.status} showExpert={false} />
                      </td>
                      <td className="py-3 pr-3 text-xs text-muted-foreground">
                        {new Date(claim.updated_at).toLocaleDateString()}
                      </td>
                      <td className="py-3">
                        <Button
                          type="button"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/insurer/claims/${claim.id}`);
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

      <div className="flex justify-end">
        <Link to="/insurer/claims">
          <Button variant="outline">View all claims</Button>
        </Link>
      </div>
    </div>
  );
}

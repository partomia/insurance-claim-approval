import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DetailHeader } from "@/components/ui/detail-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { ClaimStatusDonutChart } from "@/components/dashboard/ClaimStatusDonutChart";
import { ClaimsTimelineChart } from "@/components/dashboard/ClaimsTimelineChart";
import { agentApiJson } from "@/lib/agentApi";

interface PolicySummary {
  id: number;
  policy_number: string;
  policy_type: string;
  status: string;
  coverage_limit: number;
  deductible: number;
}

interface AgentClaim {
  id: number;
  claim_id: string;
  status: string;
  claim_amount: number;
}

interface CustomerDetail {
  id: number;
  full_name: string;
  email: string;
  policies: PolicySummary[];
  assigned_claims: AgentClaim[];
  customer_risk?: {
    customer_risk_score: number;
    prior_claims_count: number;
    policy_tenure_days: number;
    signals: string[];
  } | null;
}

interface DashboardStats {
  claims_by_status: { status: string; label: string; count: number }[];
  claims_by_month: { month: string; count: number }[];
}

export function AgentCustomer() {
  const { id } = useParams();
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [insights, setInsights] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      try {
        const [detail, stats] = await Promise.all([
          agentApiJson<CustomerDetail>(`/api/agent/customers/${id}`),
          agentApiJson<DashboardStats>(`/api/agent/customers/${id}/insights`),
        ]);
        setCustomer(detail);
        setInsights(stats);
      } catch {
        setError("Customer not found or not in your assigned queue.");
      }
    };
    load();
  }, [id]);

  if (error) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-2">
          <p className="font-medium">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (!customer) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <DetailHeader
        back={{ to: "/agent/dashboard", label: "Workspace" }}
        eyebrow="Customer profile"
        title={customer.full_name}
        subtitle={customer.email}
      />

      {customer.customer_risk && (
        <Card>
          <CardHeader>
            <CardTitle>Risk Profile</CardTitle>
          </CardHeader>
          <CardContent className="text-sm grid sm:grid-cols-3 gap-4">
            <div>
              <p className="text-muted-foreground">Risk score</p>
              <p className="text-xl font-semibold">
                {(customer.customer_risk.customer_risk_score * 100).toFixed(0)}%
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Prior claims</p>
              <p className="text-xl font-semibold">{customer.customer_risk.prior_claims_count}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Policy tenure</p>
              <p className="text-xl font-semibold">{customer.customer_risk.policy_tenure_days} days</p>
            </div>
            {customer.customer_risk.signals.length > 0 && (
              <div className="sm:col-span-3">
                <p className="text-muted-foreground mb-1">Signals</p>
                <ul className="list-disc list-inside text-warning">
                  {customer.customer_risk.signals.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Customer Claim Status</CardTitle>
          </CardHeader>
          <CardContent>
            {insights ? (
              <ClaimStatusDonutChart data={insights.claims_by_status} />
            ) : (
              <p className="text-muted-foreground text-sm">No insights available.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Claims Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            {insights ? (
              <ClaimsTimelineChart data={insights.claims_by_month} />
            ) : (
              <p className="text-muted-foreground text-sm">No timeline data.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Policies</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {customer.policies.length === 0 ? (
            <p className="text-muted-foreground text-sm">No policies on file.</p>
          ) : (
            customer.policies.map((p) => (
              <div key={p.id} className="border rounded-lg p-3 text-sm">
                <p className="font-medium">{p.policy_number} · {p.policy_type}</p>
                <p className="text-muted-foreground">
                  Coverage ${p.coverage_limit.toLocaleString()} · Deductible ${p.deductible.toLocaleString()} · {p.status}
                </p>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your Assigned Claims</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {customer.assigned_claims.map((claim) => (
            <Link
              key={claim.id}
              to={`/agent/claims/${claim.id}`}
              className="flex items-center justify-between border rounded-lg p-3 hover:border-primary/50"
            >
              <div>
                <p className="font-medium">{claim.claim_id}</p>
                <p className="text-sm text-muted-foreground">${claim.claim_amount.toLocaleString()}</p>
              </div>
              <ClaimStatusBadge status={claim.status} />
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

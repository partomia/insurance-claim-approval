import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ClaimStatusBadge } from "@/components/claim/ClaimStatusBadge";
import { agentApiJson } from "@/lib/agentApi";
import { formatEscalationSummary } from "@/lib/escalationLabels";
import { formatINR } from "@/lib/currency";

interface AgentClaim {
  id: number;
  claim_id: string;
  status: string;
  claim_amount: number;
  customer_id: number;
  customer_name: string;
  customer_email: string;
  policy_type?: string | null;
  escalation_flags: string[];
  escalation_messages?: string[];
  assigned_at?: string | null;
  created_at: string;
  fraud_score?: number | null;
  approval_probability?: number | null;
  document_count?: number;
  has_document_issues?: boolean;
}

interface CustomerSummary {
  id: number;
  full_name: string;
  email: string;
  assigned_claims_count: number;
}

const STATUS_OPTIONS = [
  "",
  "ANALYSIS_COMPLETE",
  "PENDING_REVIEW",
  "HUMAN_REVIEW",
  "SUBMISSION_READY",
  "REQUEST_MORE_INFO",
  "PROCESSING",
  "APPROVED",
  "REJECTED",
];

const URGENCY_ORDER: Record<string, number> = {
  PENDING_REVIEW: 0,
  HUMAN_REVIEW: 1,
  ANALYSIS_COMPLETE: 2,
  REQUEST_MORE_INFO: 3,
  SUBMISSION_READY: 4,
};

export function AgentClaims() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [claims, setClaims] = useState<AgentClaim[]>([]);
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [customerFilter, setCustomerFilter] = useState(searchParams.get("customer_id") ?? "");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const status = searchParams.get("status") ?? "";
    const customer = searchParams.get("customer_id") ?? "";
    setStatusFilter(status);
    setCustomerFilter(customer);
  }, [searchParams]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (statusFilter) params.set("status", statusFilter);
        if (customerFilter) params.set("customer_id", customerFilter);
        const qs = params.toString();
        const path = qs ? `/api/agent/claims?${qs}` : "/api/agent/claims";
        const [claimsData, customerData] = await Promise.all([
          agentApiJson<AgentClaim[]>(path),
          agentApiJson<CustomerSummary[]>("/api/agent/customers"),
        ]);
        setClaims(claimsData);
        setCustomers(customerData);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [statusFilter, customerFilter]);

  const sortedClaims = useMemo(
    () =>
      [...claims].sort((a, b) => {
        const ua = URGENCY_ORDER[a.status] ?? 99;
        const ub = URGENCY_ORDER[b.status] ?? 99;
        if (ua !== ub) return ua - ub;
        return (b.approval_probability ?? 0) - (a.approval_probability ?? 0);
      }),
    [claims]
  );

  const updateFilters = (status: string, customer: string) => {
    setStatusFilter(status);
    setCustomerFilter(customer);
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (customer) params.set("customer_id", customer);
    setSearchParams(params);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Motor Claims Queue"
        description="Assigned claims sorted by review urgency."
        actions={
          <>
            <Select
              className="w-full sm:w-52"
              value={customerFilter}
              onChange={(e) => updateFilters(statusFilter, e.target.value)}
              aria-label="Filter by customer"
            >
              <option value="">All customers</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name}
                </option>
              ))}
            </Select>
            <Select
              className="w-full sm:w-52"
              value={statusFilter}
              onChange={(e) => updateFilters(e.target.value, customerFilter)}
              aria-label="Filter by status"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s || "all"} value={s}>
                  {s ? s.replaceAll("_", " ") : "All statuses"}
                </option>
              ))}
            </Select>
          </>
        }
      />

      {loading ? (
        <div className="grid gap-4">
          {[0, 1, 2].map((k) => (
            <Skeleton key={k} className="h-36" />
          ))}
        </div>
      ) : sortedClaims.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No claims assigned to you yet.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {sortedClaims.map((claim) => (
            <Link key={claim.id} to={`/agent/claims/${claim.id}`}>
              <Card className="hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-lg">{claim.claim_id}</CardTitle>
                    <div className="flex items-center gap-2">
                      {claim.approval_probability != null && (
                        <span className="inline-flex rounded-full bg-success-subtle text-success px-2 py-0.5 text-xs font-semibold">
                          {(claim.approval_probability * 100).toFixed(0)}% approval
                        </span>
                      )}
                      <ClaimStatusBadge status={claim.status} />
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="text-sm space-y-1">
                  <p>
                    <span className="text-muted-foreground">Customer:</span>{" "}
                    {claim.customer_name}
                    <span className="text-muted-foreground"> · {claim.customer_email}</span>
                  </p>
                  <p>
                    <span className="text-muted-foreground">Claim amount:</span> {formatINR(claim.claim_amount)}
                    {claim.policy_type ? ` · ${claim.policy_type}` : ""}
                  </p>
                  <p>
                    <span className="text-muted-foreground">Documents:</span> {claim.document_count ?? 0}
                    {claim.has_document_issues && (
                      <span className="inline-flex items-center gap-1 text-warning ml-2">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        issues flagged
                      </span>
                    )}
                  </p>
                  {claim.fraud_score != null && (
                    <p>
                      <span className="text-muted-foreground">Risk check:</span>{" "}
                      {(claim.fraud_score * 100).toFixed(0)}%
                    </p>
                  )}
                  {formatEscalationSummary(claim.escalation_messages, claim.escalation_flags) && (
                    <p className="text-warning">
                      <span className="text-muted-foreground">Needs attention:</span>{" "}
                      {formatEscalationSummary(claim.escalation_messages, claim.escalation_flags)}
                    </p>
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
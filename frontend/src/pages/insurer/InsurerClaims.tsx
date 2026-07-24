import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ClaimHistoryCard,
  type ClaimHistoryCardData,
} from "@/components/claim/ClaimHistoryCard";
import { claimStatusLabel } from "@/lib/claimStatusLabels";
import { insurerApiJson } from "@/lib/insurerApi";

interface InsurerClaim extends ClaimHistoryCardData {
  customer_name?: string;
  customer_email?: string;
  policy_type?: string | null;
  policy_number?: string | null;
}

const STATUS_OPTIONS = ["", "SUBMITTED_TO_INSURER", "APPROVED", "REJECTED"];

export function InsurerClaims() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [claims, setClaims] = useState<InsurerClaim[]>([]);
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setStatusFilter(searchParams.get("status") ?? "");
  }, [searchParams]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (statusFilter) {
          params.set("status", statusFilter);
          params.set("all_statuses", "true");
        } else {
          params.set("all_statuses", "true");
        }
        const data = await insurerApiJson<InsurerClaim[]>(`/api/insurer/claims?${params.toString()}`);
        setClaims(Array.isArray(data) ? data : []);
      } catch {
        setClaims([]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [statusFilter]);

  const sortedClaims = useMemo(
    () =>
      [...claims].sort((a, b) => {
        const order: Record<string, number> = {
          SUBMITTED_TO_INSURER: 0,
          APPROVED: 1,
          REJECTED: 2,
        };
        const ua = order[a.status] ?? 99;
        const ub = order[b.status] ?? 99;
        if (ua !== ub) return ua - ub;
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      }),
    [claims]
  );

  const updateStatusFilter = (status: string) => {
    setStatusFilter(status);
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    setSearchParams(params);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Claims"
        description="All submissions sent to your company for final decision."
        actions={
          <Select
            className="w-full sm:w-56"
            value={statusFilter}
            onChange={(e) => updateStatusFilter(e.target.value)}
            aria-label="Filter claims by status"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s || "all"} value={s}>
                {s ? claimStatusLabel(s) : "All statuses"}
              </option>
            ))}
          </Select>
        }
      />

      {loading ? (
        <div className="space-y-4">
          {[1, 2].map((key) => (
            <Skeleton key={key} className="h-56" />
          ))}
        </div>
      ) : sortedClaims.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No claims found for this filter.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {sortedClaims.map((claim) => (
            <Link key={claim.id} to={`/insurer/claims/${claim.id}`} className="block">
              <ClaimHistoryCard
                claim={{
                  ...claim,
                  submission: {
                    policy_type: claim.policy_type ?? claim.submission?.policy_type,
                    policy_number: claim.policy_number ?? claim.submission?.policy_number,
                    location: claim.submission?.location,
                  },
                }}
              />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

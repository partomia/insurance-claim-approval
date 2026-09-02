import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, ClipboardList, Clock3, Plus } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card"; // used by empty state
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ClaimHistoryCard,
  claimNeedsAttention,
  claimStatusLabel,
  type ClaimHistoryCardData,
} from "@/components/claim/ClaimHistoryCard";
import { apiJson } from "@/lib/api";
import { CLAIM_STATUS_LABELS } from "@/lib/claimStatusLabels";

const STATUS_OPTIONS = [
  "",
  "DRAFT",
  "PROCESSING",
  "ANALYSIS_COMPLETE",
  "PENDING_REVIEW",
  "REQUEST_MORE_INFO",
  "SUBMISSION_READY",
  "SUBMITTED_TO_INSURER",
  "APPROVED",
  "REJECTED",
];

const RECENCY_ORDER: Record<string, number> = {
  REQUEST_MORE_INFO: 0,
  PENDING_REVIEW: 1,
  PROCESSING: 2,
  ANALYSIS_COMPLETE: 3,
  SUBMISSION_READY: 4,
  SUBMITTED_TO_INSURER: 5,
  APPROVED: 6,
  REJECTED: 7,
  DRAFT: 8,
};

const ACTIVE_STATUSES = new Set([
  "PROCESSING",
  "ANALYSIS_COMPLETE",
  "PENDING_REVIEW",
  "REQUEST_MORE_INFO",
  "SUBMISSION_READY",
  "SUBMITTED_TO_INSURER",
]);

export function History() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [claims, setClaims] = useState<ClaimHistoryCardData[]>([]);
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setStatusFilter(searchParams.get("status") ?? "");
  }, [searchParams]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
        const data = await apiJson<ClaimHistoryCardData[]>(`/api/claims${qs}`);
        setClaims(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error("Error fetching claims:", error);
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
        const ua = RECENCY_ORDER[a.status] ?? 99;
        const ub = RECENCY_ORDER[b.status] ?? 99;
        if (ua !== ub) return ua - ub;
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      }),
    [claims]
  );

  const stats = useMemo(() => {
    const needsAttention = claims.filter(claimNeedsAttention).length;
    const inProgress = claims.filter((c) => ACTIVE_STATUSES.has(c.status)).length;
    return {
      total: claims.length,
      needsAttention,
      inProgress,
    };
  }, [claims]);

  const updateStatusFilter = (status: string) => {
    setStatusFilter(status);
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    setSearchParams(params);
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Motor Claim History"
        description="Track every claim in one place. Items that need your action appear first."
        actions={
          <>
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
            <Link to="/claim" className="w-full sm:w-auto">
              <Button className="w-full">
                <Plus className="h-4 w-4" />
                New claim
              </Button>
            </Link>
          </>
        }
      />

      {!loading && claims.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard
            label="Total claims"
            value={stats.total}
            icon={<ClipboardList className="h-5 w-5" />}
          />
          <StatCard
            label="Need your attention"
            value={stats.needsAttention}
            tone={stats.needsAttention > 0 ? "warning" : "default"}
            icon={<AlertTriangle className="h-5 w-5" />}
          />
          <StatCard
            label="In progress"
            value={stats.inProgress}
            icon={<Clock3 className="h-5 w-5" />}
          />
        </div>
      )}

      {loading ? (
        <div className="space-y-4">
          {[1, 2].map((key) => (
            <Skeleton key={key} className="h-56" />
          ))}
        </div>
      ) : sortedClaims.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-16 text-center space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-muted">
              <ClipboardList className="h-7 w-7 text-muted-foreground" />
            </div>
            <div>
              <p className="text-lg font-medium">No claims yet</p>
              <p className="text-muted-foreground mt-1 max-w-md mx-auto">
                {statusFilter
                  ? `No claims match “${CLAIM_STATUS_LABELS[statusFilter] ?? statusFilter}”. Try another filter.`
                  : "Start a new claim to see it listed here with live status updates."}
              </p>
            </div>
            <Link to="/claim">
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Start a new claim
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {sortedClaims.map((claim) => (
            <Link key={claim.id} to={`/track/${claim.id}`} className="block">
              <ClaimHistoryCard claim={claim} />
            </Link>
          ))}
        </div>
      )}

      {!loading && sortedClaims.length > 0 && (
        <p className="text-xs text-muted-foreground text-center flex items-center justify-center gap-1">
          Click any claim to open details
          <ChevronRight className="h-3 w-3" />
        </p>
      )}
    </div>
  );
}

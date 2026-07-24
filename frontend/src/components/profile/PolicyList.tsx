import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

export interface PolicySummary {
  id: number;
  policy_number: string;
  policy_type: string;
  status: string;
  coverage_limit: number;
  deductible: number;
  co_pay_pct: number;
  document_count: number;
}

interface PolicyListProps {
  policies: PolicySummary[];
  onDeleted: () => void;
}

export function PolicyList({ policies, onDeleted }: PolicyListProps) {
  const { error, success } = useToast();
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const handleDelete = async (policyNumber: string) => {
    setDeleting(policyNumber);
    try {
      const res = await apiFetch(`/api/policies/${policyNumber}`, { method: "DELETE" });
      if (res.ok) {
        success("Policy deleted.");
        setConfirming(null);
        onDeleted();
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setDeleting(null);
    }
  };

  if (policies.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        No policies yet — upload a policy schedule above to add one.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {policies.map((policy) => (
        <div key={policy.policy_number} className="p-4 border rounded-lg">
          <div className="flex flex-wrap justify-between gap-2 items-start">
            <div>
              <p className="font-medium">
                {policy.policy_type} ({policy.policy_number})
              </p>
              <p className="text-sm text-muted-foreground">
                Coverage: ${policy.coverage_limit.toLocaleString()} · Deductible: $
                {policy.deductible.toLocaleString()} · Co-pay: {policy.co_pay_pct}%
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {policy.document_count} schedule document{policy.document_count === 1 ? "" : "s"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-full border border-success-border bg-success-subtle px-2 py-0.5 text-xs font-medium text-success capitalize">
                {policy.status.toLowerCase()}
              </span>
              {confirming === policy.policy_number ? (
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={deleting === policy.policy_number}
                    onClick={() => handleDelete(policy.policy_number)}
                  >
                    {deleting === policy.policy_number ? "Deleting..." : "Confirm"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={deleting === policy.policy_number}
                    onClick={() => setConfirming(null)}
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => setConfirming(policy.policy_number)}
                >
                  Delete
                </Button>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

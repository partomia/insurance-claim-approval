import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Shield, AlertTriangle } from "lucide-react";
import { agentApiJson } from "@/lib/agentApi";
import { insurerApiJson } from "@/lib/insurerApi";
import { useEffect, useState } from "react";

interface PolicyRequirements {
  claim_id: string;
  policy_number?: string | null;
  policy_type?: string | null;
  coverage_summary: string;
  exclusions: string[];
  key_sections: Array<Record<string, unknown>>;
  key_clauses: Array<{ section_ref?: string; summary?: string }>;
  missing_documents: string[];
  policy_clause_matches: Array<Record<string, unknown>>;
}

export function ExpertPolicyRequirements({
  claimId,
  portal = "agent",
}: {
  claimId: number;
  portal?: "agent" | "insurer";
}) {
  const [data, setData] = useState<PolicyRequirements | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const path =
      portal === "insurer"
        ? `/api/insurer/claims/${claimId}/policy-requirements`
        : `/api/agent/claims/${claimId}/policy-requirements`;
    const fetchJson = portal === "insurer" ? insurerApiJson : agentApiJson;
    fetchJson<PolicyRequirements>(path)
      .then(setData)
      .catch(() => setError("Could not load policy requirements."));
  }, [claimId, portal]);

  if (error) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">{error}</CardContent>
      </Card>
    );
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground">Loading policy requirements...</p>;
  }

  const policyLabel = data.policy_number
    ? `${data.policy_number}${data.policy_type ? ` (${data.policy_type})` : ""}`
    : "Policy";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Shield className="h-4 w-4" />
          Policy requirements
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Policy</p>
          <p className="font-medium mt-1">{policyLabel}</p>
        </div>

        {data.coverage_summary && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Coverage summary</p>
            <p className="mt-1 leading-relaxed">{data.coverage_summary}</p>
          </div>
        )}

        {data.key_clauses.length > 0 && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Key clauses</p>
            <ul className="space-y-2">
              {data.key_clauses.slice(0, 5).map((clause, i) => (
                <li key={i} className="rounded-lg border bg-muted/30 px-3 py-2">
                  <p className="font-medium text-xs text-primary">{clause.section_ref || "Clause"}</p>
                  <p className="text-muted-foreground mt-0.5">{clause.summary}</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.exclusions.length > 0 && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Exclusions</p>
            <ul className="mt-1 list-disc list-inside text-muted-foreground">
              {data.exclusions.slice(0, 4).map((ex) => (
                <li key={ex}>{ex}</li>
              ))}
            </ul>
          </div>
        )}

        {data.missing_documents.length > 0 && (
          <div className="rounded-lg border border-warning-border bg-warning-subtle px-3 py-2">
            <p className="flex items-center gap-1.5 font-medium text-warning">
              <AlertTriangle className="h-3.5 w-3.5" />
              Missing documents
            </p>
            <ul className="mt-1 list-inside list-disc">
              {data.missing_documents.map((doc) => (
                <li key={doc}>{doc}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

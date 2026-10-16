import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { insurerApiJson } from "@/lib/insurerApi";
import { BrainCircuit } from "lucide-react";

interface Disagreement {
  claim_id: number;
  claim_number: string;
  status: string;
  rules_decision?: string | null;
  approval_band?: string | null;
  fraud_band?: string | null;
  p_approve?: number | null;
  p_fraud?: number | null;
}

interface ModelVsRules {
  mode: string;
  scored: number;
  errors: number;
  compared: number;
  agreement_rate: number | null;
  fraud_review: number;
  disagreements: Disagreement[];
}

const pct = (p?: number | null) => (p == null ? "—" : `${Math.round(p * 100)}%`);

export function ModelVsRulesPanel() {
  const navigate = useNavigate();
  const [data, setData] = useState<ModelVsRules | null>(null);

  useEffect(() => {
    insurerApiJson<ModelVsRules>("/api/insurer/model-vs-rules")
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data || (data.mode === "off" && data.scored === 0)) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BrainCircuit className="h-5 w-5" />
          Model vs rules
        </CardTitle>
        <CardDescription>
          The approval and fraud model scores every decided claim in shadow mode; it never changes a decision.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Claims scored</p>
            <p className="text-lg font-semibold">{data.scored}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Agreement with rules</p>
            <p className="text-lg font-semibold">{pct(data.agreement_rate)}</p>
            <p className="text-[11px] text-muted-foreground">of {data.compared} approved or rejected</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Flagged for fraud review</p>
            <p className="text-lg font-semibold">{data.fraud_review}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Model unavailable</p>
            <p className="text-lg font-semibold">{data.errors}</p>
          </div>
        </div>

        {data.disagreements.length === 0 ? (
          <p className="text-sm text-muted-foreground">No disagreements to review.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Claim</th>
                  <th className="py-2 pr-3 font-medium">Rules</th>
                  <th className="py-2 pr-3 font-medium">Model approval</th>
                  <th className="py-2 font-medium">Model fraud</th>
                </tr>
              </thead>
              <tbody>
                {data.disagreements.map((d) => (
                  <tr
                    key={d.claim_id}
                    className="border-b last:border-0 hover:bg-muted/40 cursor-pointer"
                    onClick={() => navigate(`/insurer/claims/${d.claim_id}`)}
                  >
                    <td className="py-2 pr-3 font-medium">{d.claim_number}</td>
                    <td className="py-2 pr-3">{d.rules_decision ?? d.status}</td>
                    <td className="py-2 pr-3">
                      {pct(d.p_approve)} <span className="text-xs text-muted-foreground">{d.approval_band}</span>
                    </td>
                    <td className="py-2">
                      {pct(d.p_fraud)} <span className="text-xs text-muted-foreground">{d.fraud_band}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

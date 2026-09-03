import { Button } from "@/components/ui/button";
import { PolicyContextPreview } from "./PolicyContextPreview";
import { formatINR } from "@/lib/currency";

interface Step4Props {
  policyNumber: string;
  incidentDescription: string;
  incidentDatetime: string;
  location: string;
  claimAmount: string;
  policyContext: Record<string, unknown> | null;
  onSubmit: () => void;
  onBack: () => void;
  loading: boolean;
}

export function Step4ReviewSubmit({
  policyNumber,
  incidentDescription,
  incidentDatetime,
  location,
  claimAmount,
  policyContext,
  onSubmit,
  onBack,
  loading,
}: Step4Props) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Step 4 — Review & Submit</h2>
      <p className="text-sm text-muted-foreground">
        Review your motor claim details before submitting for AI processing.
      </p>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="p-4 border rounded-lg space-y-3">
          <h3 className="font-medium">Incident Summary</h3>
          <div className="text-sm space-y-1">
            <p><span className="text-muted-foreground">Policy:</span> {policyNumber}</p>
            <p><span className="text-muted-foreground">Date:</span> {incidentDatetime}</p>
            <p><span className="text-muted-foreground">Location:</span> {location}</p>
            <p><span className="text-muted-foreground">Estimated repair cost:</span> {formatINR(Number(claimAmount))}</p>
            <p><span className="text-muted-foreground">Description:</span> {incidentDescription}</p>
          </div>
        </div>
        <div className="p-4 border rounded-lg">
          <h3 className="font-medium mb-2">Motor Policy Context</h3>
          {policyContext ? (
            <PolicyContextPreview context={policyContext as never} />
          ) : (
            <p className="text-sm text-red-600">Policy context missing — go back to Step 2.</p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <div className="flex flex-col items-end gap-1">
          <Button onClick={onSubmit} disabled={loading || !policyContext}>
            {loading ? "Submitting..." : "Submit Motor Claim →"}
          </Button>
          {!policyContext && !loading && (
            <p className="text-xs text-muted-foreground">
              Complete Step 2 (policy papers) to enable submit.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
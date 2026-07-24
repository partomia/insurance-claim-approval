import type { ChangeEvent } from "react";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface Step1Props {
  incidentDescription: string;
  setIncidentDescription: (v: string) => void;
  incidentDatetime: string;
  setIncidentDatetime: (v: string) => void;
  location: string;
  setLocation: (v: string) => void;
  claimAmount: string;
  setClaimAmount: (v: string) => void;
  onContinue: () => void;
  loading: boolean;
}

export function Step1IncidentDetails({
  incidentDescription,
  setIncidentDescription,
  incidentDatetime,
  setIncidentDatetime,
  location,
  setLocation,
  claimAmount,
  setClaimAmount,
  onContinue,
  loading,
}: Step1Props) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Step 1 — Incident Details</h2>
      <p className="text-sm text-muted-foreground">
        Tell us what happened. We'll create a draft claim — you'll attach your policy in Step 2.
      </p>

      <FormField label="What happened?">
        <Textarea
          value={incidentDescription}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setIncidentDescription(e.target.value)}
          placeholder="Describe the incident in detail..."
          rows={4}
        />
      </FormField>

      <div className="grid grid-cols-2 gap-4">
        <FormField label="Date & Time">
          <Input
            type="datetime-local"
            value={incidentDatetime}
            onChange={(e) => setIncidentDatetime(e.target.value)}
          />
        </FormField>
        <FormField label="Location">
          <Input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="City, State"
          />
        </FormField>
      </div>

      <FormField label="Claim Amount ($)">
        <Input
          type="number"
          value={claimAmount}
          onChange={(e) => setClaimAmount(e.target.value)}
          placeholder="12000"
        />
      </FormField>

      <div className="flex justify-end gap-3 border-t pt-4">
        <Button onClick={onContinue} disabled={loading}>
          {loading ? "Creating draft..." : "Continue →"}
        </Button>
      </div>
    </div>
  );
}

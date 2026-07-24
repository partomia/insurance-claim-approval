import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { WizardStepper } from "@/components/claim/WizardStepper";
import { Step1IncidentDetails } from "@/components/claim/Step1IncidentDetails";
import { Step2PolicyPapers } from "@/components/claim/Step2PolicyPapers";
import { Step3EvidenceUpload } from "@/components/claim/Step3EvidenceUpload";
import { Step4ReviewSubmit } from "@/components/claim/Step4ReviewSubmit";
import { PageHeader } from "@/components/ui/page-header";
import { apiFetch } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

export default function ClaimWizard() {
  const navigate = useNavigate();
  const { error, success } = useToast();
  const [step, setStep] = useState(1);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [policyNumber, setPolicyNumber] = useState("");
  const [incidentDescription, setIncidentDescription] = useState("");
  const [incidentDatetime, setIncidentDatetime] = useState("");
  const [location, setLocation] = useState("");
  const [claimAmount, setClaimAmount] = useState("");
  const [policyContext, setPolicyContext] = useState<Record<string, unknown> | null>(null);

  const createDraft = async () => {
    if (!incidentDescription || !incidentDatetime || !location || !claimAmount) {
      error("Please fill in all fields.");
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch(
        "/api/claims/draft",
        {
          method: "POST",
          body: JSON.stringify({
            incident_description: incidentDescription,
            incident_datetime: new Date(incidentDatetime).toISOString(),
            location,
            claim_amount: parseFloat(claimAmount),
          }),
        },
        { json: true }
      );

      if (res.ok) {
        const data = await res.json();
        setClaimId(String(data.id));
        setStep(2);
        success("Draft claim created.");
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  const submitClaim = async () => {
    if (!claimId) return;
    setLoading(true);
    try {
      const res = await apiFetch(`/api/claims/${claimId}/submit`, { method: "POST" });
      if (res.ok) {
        success("Claim submitted successfully.");
        navigate(`/track/${claimId}`);
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="File a Claim"
        description="Complete all 4 steps to submit your claim for processing."
      />

      <WizardStepper currentStep={step} />

      <div className="rounded-xl border bg-card p-6 shadow-sm">
        {step === 1 && (
          <Step1IncidentDetails
            incidentDescription={incidentDescription}
            setIncidentDescription={setIncidentDescription}
            incidentDatetime={incidentDatetime}
            setIncidentDatetime={setIncidentDatetime}
            location={location}
            setLocation={setLocation}
            claimAmount={claimAmount}
            setClaimAmount={setClaimAmount}
            onContinue={createDraft}
            loading={loading}
          />
        )}

        {step === 2 && claimId && (
          <Step2PolicyPapers
            claimId={claimId}
            policyNumber={policyNumber}
            setPolicyNumber={setPolicyNumber}
            policyContext={policyContext}
            setPolicyContext={setPolicyContext}
            onContinue={() => setStep(3)}
            onBack={() => setStep(1)}
          />
        )}

        {step === 3 && claimId && (
          <Step3EvidenceUpload
            claimId={claimId}
            onContinue={() => setStep(4)}
            onBack={() => setStep(2)}
          />
        )}

        {step === 4 && claimId && (
          <Step4ReviewSubmit
            policyNumber={policyNumber || "—"}
            incidentDescription={incidentDescription}
            incidentDatetime={incidentDatetime}
            location={location}
            claimAmount={claimAmount}
            policyContext={policyContext}
            onSubmit={submitClaim}
            onBack={() => setStep(3)}
            loading={loading}
          />
        )}
      </div>
    </div>
  );
}

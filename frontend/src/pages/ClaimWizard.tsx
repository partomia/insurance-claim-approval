import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { WizardStepper } from "@/components/claim/WizardStepper";
import { Step1IncidentDetails } from "@/components/claim/Step1IncidentDetails";
import { Step2PolicyPapers } from "@/components/claim/Step2PolicyPapers";
import { Step3EvidenceUpload } from "@/components/claim/Step3EvidenceUpload";
import { Step4ReviewSubmit } from "@/components/claim/Step4ReviewSubmit";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, apiJson } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

interface DraftClaim {
  id: number;
  status: string;
  submission_step: number;
  policy_context_ready: boolean;
  policy_number?: string | null;
  incident_type?: string | null;
  incident_description?: string | null;
  incident_datetime?: string | null;
  location?: string | null;
  claim_amount?: number | null;
  third_party_involved: boolean;
  injuries_reported: boolean;
  tow_required: boolean;
  vehicle_make?: string | null;
  vehicle_model?: string | null;
  vehicle_year?: number | null;
  vin?: string | null;
  license_plate?: string | null;
  odometer_km?: number | null;
  driver_license_number?: string | null;
  driver_license_class?: string | null;
}

interface ClaimDoc {
  doc_type: string;
}

interface KYCStatus {
  kyc_status: string;
}

/** "2026-09-21T06:30:00Z" / with offset -> "2026-09-21T06:30" for a
 * <input type="datetime-local"> value (which has no timezone). */
function toDatetimeLocalInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function ClaimWizard() {
  const navigate = useNavigate();
  const { id: resumeId } = useParams();
  const { error, success } = useToast();
  const [step, setStep] = useState(1);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resuming, setResuming] = useState(Boolean(resumeId));

  // Step 1 — motor incident + vehicle + driver
  const [policyNumber, setPolicyNumber] = useState("");
  const [incidentType, setIncidentType] = useState("COLLISION");
  const [incidentDescription, setIncidentDescription] = useState("");
  const [incidentDatetime, setIncidentDatetime] = useState("");
  const [location, setLocation] = useState("");
  const [claimAmount, setClaimAmount] = useState("");
  const [vehicleMake, setVehicleMake] = useState("");
  const [vehicleModel, setVehicleModel] = useState("");
  const [vehicleYear, setVehicleYear] = useState("");
  const [vin, setVin] = useState("");
  const [licensePlate, setLicensePlate] = useState("");
  const [odometerKm, setOdometerKm] = useState("");
  const [driverLicenseNumber, setDriverLicenseNumber] = useState("");
  const [driverLicenseClass, setDriverLicenseClass] = useState("");
  const [thirdPartyInvolved, setThirdPartyInvolved] = useState(false);
  const [injuriesReported, setInjuriesReported] = useState(false);
  const [towRequired, setTowRequired] = useState(false);
  const [policyContext, setPolicyContext] = useState<Record<string, unknown> | null>(null);

  // Resume an existing draft (e.g. navigated here from /track/:id's
  // "Continue draft" button) instead of always starting fresh. Previously
  // there was no way back into the wizard for a draft once you left it —
  // /track/:id is read-only and this page always started a new claim.
  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;

    (async () => {
      try {
        const draft = await apiJson<DraftClaim>(`/api/claims/${resumeId}/draft`);
        if (cancelled) return;

        setClaimId(String(draft.id));
        setPolicyNumber(draft.policy_number ?? "");
        setIncidentType(draft.incident_type ?? "COLLISION");
        setIncidentDescription(draft.incident_description ?? "");
        setIncidentDatetime(toDatetimeLocalInput(draft.incident_datetime));
        setLocation(draft.location ?? "");
        setClaimAmount(draft.claim_amount != null ? String(draft.claim_amount) : "");
        setVehicleMake(draft.vehicle_make ?? "");
        setVehicleModel(draft.vehicle_model ?? "");
        setVehicleYear(draft.vehicle_year != null ? String(draft.vehicle_year) : "");
        setVin(draft.vin ?? "");
        setLicensePlate(draft.license_plate ?? "");
        setOdometerKm(draft.odometer_km != null ? String(draft.odometer_km) : "");
        setDriverLicenseNumber(draft.driver_license_number ?? "");
        setDriverLicenseClass(draft.driver_license_class ?? "");
        setThirdPartyInvolved(draft.third_party_involved);
        setInjuriesReported(draft.injuries_reported);
        setTowRequired(draft.tow_required);

        if (!draft.policy_context_ready) {
          setStep(2);
          return;
        }

        const [context, statusData, kyc] = await Promise.all([
          apiJson<Record<string, unknown>>(`/api/claims/${resumeId}/policy-context`).catch(() => null),
          apiJson<{ documents?: ClaimDoc[] }>(`/api/claims/${resumeId}/status`).catch(() => null),
          apiJson<KYCStatus>("/api/kyc/status").catch(() => null),
        ]);
        if (cancelled) return;
        if (context) setPolicyContext(context);

        const docTypes = new Set((statusData?.documents ?? []).map((d) => d.doc_type));
        const kycVerified = kyc?.kyc_status === "VERIFIED";
        const hasDamagePhoto = docTypes.has("DAMAGE_PHOTO");
        const hasDriverLicense = docTypes.has("DRIVER_LICENSE");
        const hasPoliceReport = docTypes.has("POLICE_REPORT");
        const policeRequired = draft.third_party_involved || draft.injuries_reported;

        const evidenceComplete =
          hasDamagePhoto && (kycVerified || hasDriverLicense) && (!policeRequired || hasPoliceReport);

        setStep(evidenceComplete ? 4 : 3);
      } catch {
        if (!cancelled) {
          error("Could not load that draft claim — starting a new one.");
        }
      } finally {
        if (!cancelled) setResuming(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]);

  const createDraft = async () => {
    if (!incidentDescription || !incidentDatetime || !location || !claimAmount) {
      error("Please fill in incident description, date/time, location, and estimated cost.");
      return;
    }
    setLoading(true);
    try {
      const body: Record<string, unknown> = {
        incident_type: incidentType,
        incident_description: incidentDescription,
        incident_datetime: new Date(incidentDatetime).toISOString(),
        location,
        claim_amount: parseFloat(claimAmount),
        third_party_involved: thirdPartyInvolved,
        injuries_reported: injuriesReported,
        tow_required: towRequired,
      };
      if (vehicleMake) body.vehicle_make = vehicleMake;
      if (vehicleModel) body.vehicle_model = vehicleModel;
      if (vehicleYear) body.vehicle_year = parseInt(vehicleYear, 10);
      if (vin) body.vin = vin.trim().toUpperCase();
      if (licensePlate) body.license_plate = licensePlate.trim().toUpperCase();
      if (odometerKm) body.odometer_km = parseInt(odometerKm, 10);
      if (driverLicenseNumber) body.driver_license_number = driverLicenseNumber;
      if (driverLicenseClass) body.driver_license_class = driverLicenseClass;

      const res = await apiFetch(
        "/api/claims/draft",
        { method: "POST", body: JSON.stringify(body) },
        { json: true },
      );

      if (res.ok) {
        const data = await res.json();
        setClaimId(String(data.id));
        setStep(2);
        success("Draft motor claim created.");
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
        success("Motor claim submitted successfully.");
        navigate(`/track/${claimId}`);
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  if (resuming) {
    return (
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          title="File a Motor Claim"
          description="Loading your draft claim..."
        />
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="File a Motor Claim"
        description={
          resumeId
            ? "Continuing your draft claim — pick up where you left off."
            : "Complete all 4 steps to submit your motor-vehicle claim for processing."
        }
      />

      <WizardStepper currentStep={step} />

      <div className="rounded-xl border bg-card p-6 shadow-sm">
        {step === 1 && (
          <Step1IncidentDetails
            incidentType={incidentType}
            setIncidentType={setIncidentType}
            incidentDescription={incidentDescription}
            setIncidentDescription={setIncidentDescription}
            incidentDatetime={incidentDatetime}
            setIncidentDatetime={setIncidentDatetime}
            location={location}
            setLocation={setLocation}
            claimAmount={claimAmount}
            setClaimAmount={setClaimAmount}
            vehicleMake={vehicleMake}
            setVehicleMake={setVehicleMake}
            vehicleModel={vehicleModel}
            setVehicleModel={setVehicleModel}
            vehicleYear={vehicleYear}
            setVehicleYear={setVehicleYear}
            vin={vin}
            setVin={setVin}
            licensePlate={licensePlate}
            setLicensePlate={setLicensePlate}
            odometerKm={odometerKm}
            setOdometerKm={setOdometerKm}
            driverLicenseNumber={driverLicenseNumber}
            setDriverLicenseNumber={setDriverLicenseNumber}
            driverLicenseClass={driverLicenseClass}
            setDriverLicenseClass={setDriverLicenseClass}
            thirdPartyInvolved={thirdPartyInvolved}
            setThirdPartyInvolved={setThirdPartyInvolved}
            injuriesReported={injuriesReported}
            setInjuriesReported={setInjuriesReported}
            towRequired={towRequired}
            setTowRequired={setTowRequired}
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
            thirdPartyInvolved={thirdPartyInvolved}
            injuriesReported={injuriesReported}
            towRequired={towRequired}
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

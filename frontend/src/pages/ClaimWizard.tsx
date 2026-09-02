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

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="File a Motor Claim"
        description="Complete all 4 steps to submit your motor-vehicle claim for processing."
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

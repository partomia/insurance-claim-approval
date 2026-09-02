import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FileInput } from "@/components/ui/file-input";
import { FormField } from "@/components/ui/form-field";
import { apiFetch, apiJson } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import { formatApiError, useToast } from "@/components/ui/toast";

interface Step3Props {
  claimId: string;
  thirdPartyInvolved: boolean;
  injuriesReported: boolean;
  towRequired: boolean;
  onContinue: () => void;
  onBack: () => void;
}

interface KYCStatus {
  kyc_status: string;
}

export function Step3EvidenceUpload({
  claimId,
  thirdPartyInvolved,
  injuriesReported,
  towRequired,
  onContinue,
  onBack,
}: Step3Props) {
  const { error, success } = useToast();
  const [damagePhotos, setDamagePhotos] = useState<File[]>([]);
  const [repairEstimate, setRepairEstimate] = useState<File | null>(null);
  const [driverLicense, setDriverLicense] = useState<File | null>(null);
  const [vehicleRegistration, setVehicleRegistration] = useState<File | null>(null);
  const [policeReport, setPoliceReport] = useState<File | null>(null);
  const [towingInvoice, setTowingInvoice] = useState<File | null>(null);
  const [thirdPartyStatement, setThirdPartyStatement] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [kycVerified, setKycVerified] = useState(false);

  const policeRequired = thirdPartyInvolved || injuriesReported;

  useEffect(() => {
    apiJson<KYCStatus>("/api/kyc/status")
      .then((s) => setKycVerified(s.kyc_status === "VERIFIED"))
      .catch(() => setKycVerified(false));
  }, []);

  const uploadEvidence = async () => {
    if (damagePhotos.length === 0) {
      error("Upload at least one damage photo.");
      return;
    }
    if (!kycVerified && !driverLicense) {
      error("Complete KYC in your profile, or upload driver's licence for this session.");
      return;
    }
    if (policeRequired && !policeReport) {
      error("Police / FIR report is required when third parties or injuries are involved.");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      if (driverLicense) fd.append("driver_license", driverLicense);
      damagePhotos.forEach((p) => fd.append("damage_photos", p));
      if (repairEstimate) fd.append("repair_estimate", repairEstimate);
      if (vehicleRegistration) fd.append("vehicle_registration", vehicleRegistration);
      if (policeReport) fd.append("police_report", policeReport);
      if (towingInvoice) fd.append("towing_invoice", towingInvoice);
      if (thirdPartyStatement) fd.append("third_party_statement", thirdPartyStatement);

      const res = await apiFetch(
        `/api/claims/${claimId}/evidence`,
        {
          method: "POST",
          headers: authHeaders(),
          body: fd,
        },
        { redirectOn401: true },
      );
      if (res.ok) {
        success("Documents uploaded.");
        onContinue();
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Accident Evidence & Supporting Documents</h2>
      <p className="text-sm text-muted-foreground">
        Upload damage photos, repair estimates, and identity documents.{" "}
        {kycVerified
          ? "Your identity is already verified — no need to upload driver's licence again."
          : "Complete KYC once in Profile to skip licence upload on future claims."}
      </p>

      {!kycVerified && (
        <FormField label="Driver's licence (required until KYC complete)">
          <FileInput
            accept=".pdf,.png,.jpg,.jpeg"
            placeholder="Upload driver's licence"
            onFilesSelected={(files) => setDriverLicense(files[0] ?? null)}
          />
        </FormField>
      )}

      <FormField label="Damage photos (required)">
        <FileInput
          accept=".png,.jpg,.jpeg,.heic,.heif"
          multiple
          placeholder="Upload one or more photos of the vehicle damage"
          onFilesSelected={setDamagePhotos}
        />
      </FormField>

      <FormField label="Repair estimate / garage invoice (recommended)">
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          placeholder="Upload the garage's repair estimate or invoice"
          onFilesSelected={(files) => setRepairEstimate(files[0] ?? null)}
        />
      </FormField>

      <FormField label="Vehicle registration / RC (optional)">
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          placeholder="Upload the vehicle registration certificate"
          onFilesSelected={(files) => setVehicleRegistration(files[0] ?? null)}
        />
      </FormField>

      <FormField
        label={
          policeRequired
            ? "Police / FIR report (required — third party or injuries reported)"
            : "Police / FIR report (optional)"
        }
      >
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          placeholder="Upload police report or FIR"
          onFilesSelected={(files) => setPoliceReport(files[0] ?? null)}
        />
      </FormField>

      {towRequired && (
        <FormField label="Towing invoice (recommended)">
          <FileInput
            accept=".pdf,.png,.jpg,.jpeg"
            placeholder="Upload the towing invoice"
            onFilesSelected={(files) => setTowingInvoice(files[0] ?? null)}
          />
        </FormField>
      )}

      {thirdPartyInvolved && (
        <FormField label="Third-party statement (optional)">
          <FileInput
            accept=".pdf,.png,.jpg,.jpeg"
            placeholder="Signed statement from the other party"
            onFilesSelected={(files) => setThirdPartyStatement(files[0] ?? null)}
          />
        </FormField>
      )}

      <div className="flex gap-3 border-t pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={uploadEvidence} disabled={loading}>
          {loading ? "Uploading..." : "Continue"}
        </Button>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FileInput } from "@/components/ui/file-input";
import { FormField } from "@/components/ui/form-field";
import { apiFetch, apiJson } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import { formatApiError, useToast } from "@/components/ui/toast";

interface Step3Props {
  claimId: string;
  onContinue: () => void;
  onBack: () => void;
}

interface KYCStatus {
  kyc_status: string;
}

export function Step3EvidenceUpload({ claimId, onContinue, onBack }: Step3Props) {
  const { error, success } = useToast();
  const [proofs, setProofs] = useState<File[]>([]);
  const [govId, setGovId] = useState<File | null>(null);
  const [policeReport, setPoliceReport] = useState<File | null>(null);
  const [medicalBills, setMedicalBills] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [kycVerified, setKycVerified] = useState(false);

  useEffect(() => {
    apiJson<KYCStatus>("/api/kyc/status")
      .then((s) => setKycVerified(s.kyc_status === "VERIFIED"))
      .catch(() => setKycVerified(false));
  }, []);

  const uploadEvidence = async () => {
    if (proofs.length === 0) {
      error("Upload at least one supporting document (bills, reports, photos, FIR, receipts).");
      return;
    }
    if (!kycVerified && !govId) {
      error("Complete KYC in your profile, or upload government ID for this session.");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      if (govId) fd.append("gov_id", govId);
      proofs.forEach((p) => fd.append("proofs", p));
      if (policeReport) fd.append("police_report", policeReport);
      if (medicalBills) fd.append("medical_bills", medicalBills);

      const res = await apiFetch(`/api/claims/${claimId}/evidence`, {
        method: "POST",
        headers: authHeaders(),
        body: fd,
      }, { redirectOn401: true });
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
      <h2 className="text-xl font-semibold">Supporting Documents</h2>
      <p className="text-sm text-muted-foreground">
        Upload bills, medical reports, photos, FIR, or receipts. {kycVerified ? "Your identity is already verified — no need to upload ID again." : "Complete KYC once in Profile to skip ID upload on future claims."}
      </p>

      {!kycVerified && (
        <FormField label="Government ID (required until KYC complete)">
          <FileInput
            accept=".pdf,.png,.jpg,.jpeg"
            placeholder="Upload government ID"
            onFilesSelected={(files) => setGovId(files[0] ?? null)}
          />
        </FormField>
      )}

      <FormField label="Supporting documents (required)">
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          multiple
          placeholder="Upload bills, reports, photos, or receipts"
          onFilesSelected={setProofs}
        />
      </FormField>

      <FormField label="FIR / Police report (optional)">
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          placeholder="Upload police report (optional)"
          onFilesSelected={(files) => setPoliceReport(files[0] ?? null)}
        />
      </FormField>

      <FormField label="Medical bills / reports (optional)">
        <FileInput
          accept=".pdf,.png,.jpg,.jpeg"
          placeholder="Upload medical bills (optional)"
          onFilesSelected={(files) => setMedicalBills(files[0] ?? null)}
        />
      </FormField>

      <div className="flex gap-3 border-t pt-4">
        <Button variant="outline" onClick={onBack}>Back</Button>
        <Button onClick={uploadEvidence} disabled={loading}>{loading ? "Uploading..." : "Continue"}</Button>
      </div>
    </div>
  );
}

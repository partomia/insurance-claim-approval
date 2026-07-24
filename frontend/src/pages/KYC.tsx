import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FileInput } from "@/components/ui/file-input";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/status-dot";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, apiJson } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import { formatApiError, useToast } from "@/components/ui/toast";
import { Shield } from "lucide-react";

interface KYCStatus {
  kyc_status: string;
  gov_id_uploaded: boolean;
  face_verified: boolean;
  mobile_verified: boolean;
}

export function KYC() {
  const navigate = useNavigate();
  const { error, success } = useToast();
  const [status, setStatus] = useState<KYCStatus | null>(null);
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const data = await apiJson<KYCStatus>("/api/kyc/status");
    setStatus(data);
    if (data.kyc_status === "VERIFIED") navigate("/dashboard");
  }, [navigate]);

  useEffect(() => {
    refresh().catch(console.error);
  }, [refresh]);

  const uploadGovId = async (file: File) => {
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("gov_id", file);
      const res = await apiFetch("/api/kyc/gov-id", { method: "POST", headers: authHeaders(), body: fd });
      if (!res.ok) throw new Error(formatApiError((await res.json()).detail));
      success("Government ID uploaded");
      await refresh();
    } catch (e) {
      error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const verifyFace = async () => {
    setLoading(true);
    try {
      await apiJson("/api/kyc/verify-face", { method: "POST" });
      success("Face verification complete");
      await refresh();
    } catch (e) {
      error(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  };

  const sendOtp = async () => {
    if (phone.length < 10) {
      error("Enter a valid mobile number");
      return;
    }
    await apiJson("/api/kyc/send-mobile-otp", { method: "POST", body: JSON.stringify({ phone }) }, { json: true });
    success("OTP sent (demo: 112233)");
  };

  const verifyMobile = async () => {
    setLoading(true);
    try {
      await apiJson("/api/kyc/verify-mobile", { method: "POST", body: JSON.stringify({ phone, otp }) }, { json: true });
      success("Mobile verified — KYC complete!");
      await refresh();
    } catch (e) {
      error(e instanceof Error ? e.message : "OTP verification failed");
    } finally {
      setLoading(false);
    }
  };

  if (!status) {
    return (
      <div className="mx-auto max-w-2xl space-y-8">
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-9 w-60" />
          <Skeleton className="h-4 w-full max-w-md" />
        </div>
        <div className="grid gap-3">
          {[0, 1, 2].map((k) => (
            <Skeleton key={k} className="h-16" />
          ))}
        </div>
      </div>
    );
  }

  const steps = [
    { done: status.gov_id_uploaded, label: "Government ID", desc: "Upload Aadhaar or PAN (once)" },
    { done: status.face_verified, label: "Face Verification", desc: "Quick liveness check" },
    { done: status.mobile_verified, label: "Mobile OTP", desc: "Verify registered number" },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <PageHeader
        eyebrow="One-time verification"
        title="Complete KYC"
        description="Verify once. Never upload government ID again for every claim."
      />

      <div className="grid gap-3">
        {steps.map((s) => (
          <div key={s.label} className="flex items-center gap-3 rounded-lg border p-4">
            <StatusDot done={s.done} />
            <div>
              <p className="font-medium">{s.label}</p>
              <p className="text-sm text-muted-foreground">{s.desc}</p>
            </div>
          </div>
        ))}
      </div>

      {!status.gov_id_uploaded && (
        <Card>
          <CardHeader><CardTitle className="text-base">Step 1 — Government ID</CardTitle></CardHeader>
          <CardContent>
            <FileInput
              accept=".pdf,.png,.jpg,.jpeg"
              placeholder="Upload Aadhaar or PAN"
              onFilesSelected={(files) => files[0] && uploadGovId(files[0])}
            />
          </CardContent>
        </Card>
      )}

      {status.gov_id_uploaded && !status.face_verified && (
        <Card>
          <CardHeader><CardTitle className="text-base">Step 2 — Face Verification</CardTitle></CardHeader>
          <CardContent>
            <Button onClick={verifyFace} disabled={loading}>Verify Face (Demo)</Button>
          </CardContent>
        </Card>
      )}

      {status.face_verified && !status.mobile_verified && (
        <Card>
          <CardHeader><CardTitle className="text-base">Step 3 — Mobile Verification</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <FormField label="Mobile Number">
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="9876543210" />
            </FormField>
            <div className="flex gap-3 border-t pt-4">
              <Button variant="outline" onClick={sendOtp}>Send OTP</Button>
            </div>
            <FormField label="OTP">
              <Input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="112233" />
            </FormField>
            <div className="flex gap-3 border-t pt-4">
              <Button onClick={verifyMobile} disabled={loading}>Verify Mobile</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status.kyc_status === "VERIFIED" && (
        <div className="flex items-center gap-3 rounded-xl border border-success-border bg-success-subtle p-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-success/15 text-success">
            <Shield className="h-6 w-6" />
          </span>
          <div>
            <p className="font-medium">KYC Verified</p>
            <Button className="mt-2" onClick={() => navigate("/policies/connect")}>Connect Insurance Policy</Button>
          </div>
        </div>
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { UploadPolicyDocument } from "@/components/profile/UploadPolicyDocument";
import { PolicyList, type PolicySummary } from "@/components/profile/PolicyList";
import { apiJson } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";
import { ChevronDown, Shield } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";

interface Provider {
  id: number;
  name: string;
  slug: string;
}

export function ConnectPolicy() {
  const { error, success } = useToast();
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerSlug, setProviderSlug] = useState("");
  const [policyNumber, setPolicyNumber] = useState("");
  const [dob, setDob] = useState("");
  const [otp, setOtp] = useState("");
  const [otpStep, setOtpStep] = useState<"form" | "otp" | "done">("form");
  const [otpOpen, setOtpOpen] = useState(false);
  const [connected, setConnected] = useState<string | null>(null);

  const loadPolicies = useCallback(() => {
    apiJson<PolicySummary[]>("/api/policies/me")
      .then((data) => setPolicies(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, []);

  useEffect(() => {
    loadPolicies();
    apiJson<Provider[]>("/api/policies/providers").then(setProviders).catch(console.error);
  }, [loadPolicies]);

  const initiate = async () => {
    if (!providerSlug || !policyNumber || !dob) {
      error("Fill all fields");
      return;
    }
    try {
      await apiJson(
        "/api/policies/connect/initiate",
        {
          method: "POST",
          body: JSON.stringify({
            provider_slug: providerSlug,
            policy_number: policyNumber,
            date_of_birth: new Date(dob).toISOString(),
          }),
        },
        { json: true }
      );
      setOtpStep("otp");
      success("OTP sent (demo: 112233)");
    } catch (e) {
      error(formatApiError(e instanceof Error ? e.message : "Could not initiate"));
    }
  };

  const verify = async () => {
    try {
      const result = await apiJson<{ policy_number: string }>(
        "/api/policies/connect/verify",
        {
          method: "POST",
          body: JSON.stringify({
            provider_slug: providerSlug,
            policy_number: policyNumber,
            date_of_birth: new Date(dob).toISOString(),
            otp,
          }),
        },
        { json: true }
      );
      setConnected(result.policy_number);
      setOtpStep("done");
      success("Policy connected!");
      loadPolicies();
    } catch (e) {
      error(formatApiError(e instanceof Error ? e.message : "Verification failed"));
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <PageHeader
        eyebrow="Policy connection"
        title="Connect your motor insurance policy"
        description="Upload your policy schedule for instant AI indexing, or connect via your insurer portal."
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload motor policy schedule (recommended)</CardTitle>
        </CardHeader>
        <CardContent>
          <UploadPolicyDocument onCreated={loadPolicies} />
        </CardContent>
      </Card>

      <div className="rounded-xl border bg-card overflow-hidden">
        <button
          type="button"
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-muted/40 transition-colors"
          onClick={() => setOtpOpen((v) => !v)}
        >
          <span className="text-sm font-medium">Alternative: connect via insurer portal (OTP)</span>
          <ChevronDown className={`h-4 w-4 transition-transform ${otpOpen ? "rotate-180" : ""}`} />
        </button>
        {otpOpen && (
          <div className="px-4 pb-4 border-t">
            {otpStep === "done" ? (
              <div className="pt-4 flex items-center gap-4">
                <Shield className="h-8 w-8 text-success" />
                <div>
                  <p className="font-medium">Policy {connected} connected</p>
                  <Link to="/claim">
                    <Button className="mt-3" size="sm">
                      Start a Claim
                    </Button>
                  </Link>
                </div>
              </div>
            ) : (
              <div className="pt-4 space-y-4">
                <FormField label="Insurance Company">
                  <Select
                    value={providerSlug}
                    onChange={(e) => setProviderSlug(e.target.value)}
                  >
                    <option value="">Select provider</option>
                    {providers.map((p) => (
                      <option key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Policy Number">
                  <Input
                    value={policyNumber}
                    onChange={(e) => setPolicyNumber(e.target.value)}
                    placeholder="HLT-123456789"
                  />
                </FormField>
                <FormField label="Date of Birth">
                  <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
                </FormField>
                {otpStep === "form" ? (
                  <div className="flex gap-3 border-t pt-4">
                    <Button onClick={initiate}>Send OTP</Button>
                  </div>
                ) : (
                  <>
                    <FormField label="OTP">
                      <Input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="112233" />
                    </FormField>
                    <div className="flex gap-3 border-t pt-4">
                      <Button onClick={verify}>Connect Policy</Button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your connected motor policies</CardTitle>
        </CardHeader>
        <CardContent>
          <PolicyList policies={policies} onDeleted={loadPolicies} />
        </CardContent>
      </Card>
    </div>
  );
}

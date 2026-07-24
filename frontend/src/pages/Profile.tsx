import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/status-dot";
import { Skeleton } from "@/components/ui/skeleton";
import { PolicyList, type PolicySummary } from "@/components/profile/PolicyList";
import { apiJson } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";
import { Shield } from "lucide-react";

interface CustomerProfile {
  id: number;
  email: string;
  full_name: string;
  kyc_status: string;
  gov_id_uploaded: boolean;
  face_verified: boolean;
  mobile_verified: boolean;
  phone?: string | null;
  saved_vehicles: Record<string, unknown>[];
  saved_hospitals: Record<string, unknown>[];
  dependents: Record<string, unknown>[];
}

export function Profile() {
  const { error, success } = useToast();
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [extended, setExtended] = useState<CustomerProfile | null>(null);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiJson<PolicySummary[]>("/api/policies/me");
      setPolicies(Array.isArray(data) ? data : []);
    } catch (err) {
      error(formatApiError(err instanceof Error ? err.message : "Failed to load policies"));
      setPolicies([]);
    } finally {
      setLoading(false);
    }
  }, [error]);

  const loadProfile = useCallback(async () => {
    setProfileLoading(true);
    try {
      const [basic, full] = await Promise.all([
        apiJson<{ full_name: string; email: string }>("/auth/me"),
        apiJson<CustomerProfile>("/api/kyc/profile"),
      ]);
      setFullName(basic.full_name);
      setEmail(basic.email);
      setExtended(full);
    } catch (err) {
      error(formatApiError(err instanceof Error ? err.message : "Failed to load profile"));
    } finally {
      setProfileLoading(false);
    }
  }, [error]);

  useEffect(() => {
    loadPolicies();
    loadProfile();
  }, [loadPolicies, loadProfile]);

  const handleSave = async () => {
    const trimmed = fullName.trim();
    if (!trimmed) {
      error("Full name is required.");
      return;
    }
    setSaving(true);
    try {
      await apiJson("/auth/me", { method: "PATCH", body: JSON.stringify({ full_name: trimmed }) }, { json: true });
      success("Profile updated.");
    } catch (err) {
      error(formatApiError(err instanceof Error ? err.message : "Failed to save profile"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title="Customer Profile"
        description="Identity, connected policies, and saved claim information."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Shield className="h-5 w-5" /> KYC Status</CardTitle>
          <CardDescription>Government ID is verified once and reused for all claims.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {extended ? (
            <>
              <div className="flex flex-wrap gap-4 text-sm">
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot size="sm" done={extended.gov_id_uploaded} /> Gov ID
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot size="sm" done={extended.face_verified} /> Face
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot size="sm" done={extended.mobile_verified} /> Mobile
                </span>
              </div>
              <p className="text-sm capitalize">Status: {extended.kyc_status.toLowerCase()}</p>
              {extended.kyc_status !== "VERIFIED" && (
                <Link to="/kyc"><Button size="sm">Complete KYC</Button></Link>
              )}
            </>
          ) : (
            <Skeleton className="h-16 w-full" />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Personal Information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {profileLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="name">Full Name</Label>
                <Input id="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" value={email} disabled />
              </div>
              {extended?.phone && <p className="text-sm text-muted-foreground">Phone: {extended.phone}</p>}
              <Button onClick={handleSave} disabled={saving}>{saving ? "Saving..." : "Save Changes"}</Button>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Connected Policies</CardTitle>
          <CardDescription>Policies linked from your insurance provider.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Link to="/policies/connect"><Button variant="outline">Connect New Policy</Button></Link>
          {loading ? <p className="text-sm text-muted-foreground">Loading...</p> : <PolicyList policies={policies} onDeleted={loadPolicies} />}
        </CardContent>
      </Card>

      {extended && (extended.saved_hospitals.length > 0 || extended.saved_vehicles.length > 0) && (
        <Card>
          <CardHeader><CardTitle>Saved for Claims</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            {extended.saved_hospitals.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Hospitals</p>
                <div className="flex flex-wrap gap-2">
                  {extended.saved_hospitals
                    .map((h) => String((h as { name?: string }).name ?? ""))
                    .filter(Boolean)
                    .map((name) => (
                      <span
                        key={name}
                        className="inline-flex items-center rounded-full border bg-muted/40 px-2.5 py-1 text-xs font-medium"
                      >
                        {name}
                      </span>
                    ))}
                </div>
              </div>
            )}
            {extended.saved_vehicles.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Vehicles</p>
                <div className="flex flex-wrap gap-2">
                  {extended.saved_vehicles
                    .map((v) => String((v as { make?: string }).make ?? ""))
                    .filter(Boolean)
                    .map((make) => (
                      <span
                        key={make}
                        className="inline-flex items-center rounded-full border bg-muted/40 px-2.5 py-1 text-xs font-medium"
                      >
                        {make}
                      </span>
                    ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

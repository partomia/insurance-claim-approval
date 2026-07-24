import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileInput } from "@/components/ui/file-input";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatApiError, useToast } from "@/components/ui/toast";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface PolicyOption {
  policy_number: string;
  policy_type: string;
  coverage_limit: number;
}

export function ClaimForm() {
  const [policies, setPolicies] = useState<PolicyOption[]>([]);
  const [policyNumber, setPolicyNumber] = useState("");
  const [incident, setIncident] = useState("");
  const [incidentDatetime, setIncidentDatetime] = useState("");
  const [location, setLocation] = useState("");
  const [amount, setAmount] = useState("");
  const [proofs, setProofs] = useState<FileList | null>(null);
  const [govId, setGovId] = useState<File | null>(null);
  const [policeReport, setPoliceReport] = useState<File | null>(null);
  const [medicalBills, setMedicalBills] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingPolicies, setLoadingPolicies] = useState(true);
  const navigate = useNavigate();
  const { error, success } = useToast();

  useEffect(() => {
    const loadPolicies = async () => {
      try {
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/policies/me`, {
          headers: authHeaders(),
        });
        if (response.ok) {
          const data: PolicyOption[] = await response.json();
          setPolicies(data);
          if (data.length > 0) {
            setPolicyNumber(data[0].policy_number);
          }
        } else if (response.status === 401) {
          navigate("/auth");
        }
      } catch (error) {
        console.error("Error loading policies:", error);
      } finally {
        setLoadingPolicies(false);
      }
    };
    loadPolicies();
  }, [navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!govId) {
      error("Government ID proof is required.");
      return;
    }
    if (!policyNumber) {
      error("No policy available. Log out and sign in again to create one.");
      return;
    }

    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("policy_number", policyNumber);
      formData.append("incident_description", incident);
      formData.append("incident_datetime", new Date(incidentDatetime).toISOString());
      formData.append("location", location);
      formData.append("claim_amount", amount);
      formData.append("gov_id", govId);
      if (proofs) {
        for (let i = 0; i < proofs.length; i++) {
          formData.append("proofs", proofs[i]);
        }
      }
      if (policeReport) formData.append("police_report", policeReport);
      if (medicalBills) formData.append("medical_bills", medicalBills);

      const response = await fetch(`${import.meta.env.VITE_API_URL}/api/claims/submit`, {
        method: "POST",
        headers: authHeaders(),
        body: formData,
      });

      if (response.ok) {
        const data = await response.json();
        success("Claim submitted.");
        navigate(`/track/${data.id}`);
      } else {
        const err = await response.json();
        error(formatApiError(err.detail));
      }
    } catch {
      error("Failed to submit claim.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingPolicies) {
    return <div className="max-w-2xl mx-auto p-8">Loading your policies...</div>;
  }

  return (
    <div className="max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle>Submit a Claim</CardTitle>
          <CardDescription>
            Provide incident details and upload supporting documents to start automated processing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {policies.length === 0 ? (
            <p className="text-muted-foreground">
              No policies found. Please log out and sign in again.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <FormField label="Policy" htmlFor="policyNumber">
                <Select
                  id="policyNumber"
                  value={policyNumber}
                  onChange={(e) => setPolicyNumber(e.target.value)}
                  required
                >
                  {policies.map((p) => (
                    <option key={p.policy_number} value={p.policy_number}>
                      {p.policy_number} — {p.policy_type} (${p.coverage_limit.toLocaleString()} limit)
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="Incident Description" htmlFor="incident">
                <Textarea
                  id="incident"
                  placeholder="Describe what happened..."
                  value={incident}
                  onChange={(e) => setIncident(e.target.value)}
                  required
                />
              </FormField>
              <FormField label="Date & Time of Incident" htmlFor="incidentDatetime">
                <Input
                  id="incidentDatetime"
                  type="datetime-local"
                  value={incidentDatetime}
                  onChange={(e) => setIncidentDatetime(e.target.value)}
                  required
                />
              </FormField>
              <FormField label="Location" htmlFor="location">
                <Input
                  id="location"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="City, State"
                  required
                />
              </FormField>
              <FormField label="Claim Amount ($)" htmlFor="amount">
                <Input
                  id="amount"
                  type="number"
                  step="0.01"
                  placeholder="5000.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                />
              </FormField>
              <FormField label="Proof Documents (images, PDFs)">
                <FileInput
                  multiple
                  accept="image/*,.pdf"
                  placeholder="Upload proof documents"
                  onChange={(files) => setProofs(files)}
                />
              </FormField>
              <FormField label="Government ID Proof (required)">
                <FileInput
                  accept="image/*,.pdf"
                  placeholder="Upload government ID"
                  onFilesSelected={(files) => setGovId(files[0] ?? null)}
                />
              </FormField>
              <FormField label="Police Report (optional)">
                <FileInput
                  accept="image/*,.pdf"
                  placeholder="Upload police report"
                  onFilesSelected={(files) => setPoliceReport(files[0] ?? null)}
                />
              </FormField>
              <FormField label="Medical Bills / Invoices (optional)">
                <FileInput
                  accept="image/*,.pdf"
                  placeholder="Upload medical bills or invoices"
                  onFilesSelected={(files) => setMedicalBills(files[0] ?? null)}
                />
              </FormField>
              <div className="pt-4 border-t">
                <Button type="submit" className="w-full" disabled={submitting}>
                  {submitting ? "Submitting..." : "Submit Claim"}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

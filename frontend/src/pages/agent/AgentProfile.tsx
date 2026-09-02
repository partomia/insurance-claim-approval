import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { agentApiJson } from "@/lib/agentApi";
import { formatApiError, useToast } from "@/components/ui/toast";

interface AgentProfile {
  id: number;
  email: string;
  full_name: string;
  department?: string | null;
}

export function AgentProfile() {
  const { success, error } = useToast();
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    agentApiJson<AgentProfile>("/agent/auth/me").then((data) => {
      setProfile(data);
      setFullName(data.full_name);
      setDepartment(data.department ?? "");
    });
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await agentApiJson<AgentProfile>("/agent/auth/me", {
        method: "PATCH",
        body: JSON.stringify({
          full_name: fullName,
          department: department || null,
        }),
      }, { json: true });
      setProfile(updated);
      success("Profile updated.");
    } catch (err) {
      error(formatApiError(err instanceof Error ? err.message : "Update failed"));
    } finally {
      setSaving(false);
    }
  };

  if (!profile) {
    return (
      <div className="mx-auto max-w-lg space-y-6">
        <Skeleton className="h-16" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <PageHeader
        eyebrow="Expert account"
        title="Agent Profile"
        description="Update your staff profile."
      />

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" value={profile.email} disabled />
            </div>
            <div className="space-y-2">
              <Label htmlFor="fullName">Full Name</Label>
              <Input
                id="fullName"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="department">Department</Label>
              <Input
                id="department"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="Motor Claims Review"
              />
            </div>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save Changes"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

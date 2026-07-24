import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { UserCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { apiFetch, apiJson } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

interface AvailableAgent {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
}

interface AssignPolicyAgentModalProps {
  claimId: string;
  open: boolean;
  onClose: () => void;
  onAssigned: () => void;
}

export function AssignPolicyAgentModal({
  claimId,
  open,
  onClose,
  onAssigned,
}: AssignPolicyAgentModalProps) {
  const { error, success } = useToast();
  const [agents, setAgents] = useState<AvailableAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<number | "">("");
  const [agentName, setAgentName] = useState("");
  const [useCustomName, setUseCustomName] = useState(false);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    apiJson<AvailableAgent[]>("/api/agents/available")
      .then(setAgents)
      .catch(() => setAgents([]));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!useCustomName && selectedAgentId === "") {
      error("Select a claim expert.");
      return;
    }
    if (useCustomName && !agentName.trim()) {
      error("Enter an agent name or email.");
      return;
    }
    setLoading(true);
    try {
      const body = useCustomName
        ? { agent_name: agentName.trim() }
        : { agent_id: selectedAgentId };
      const res = await apiFetch(
        `/api/claims/${claimId}/assign`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
        { json: true }
      );
      if (res.ok) {
        const data = await res.json();
        success(`Claim assigned to ${data.assigned_agent ?? "agent"}.`);
        setSelectedAgentId("");
        setAgentName("");
        onAssigned();
        onClose();
      } else {
        const err = await res.json();
        error(formatApiError(err.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assign-agent-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/70 backdrop-blur-[2px]"
        aria-label="Close dialog"
        onClick={onClose}
      />

      <div
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-2xl"
      >
        <div className="flex items-start gap-4 border-b border-warning-border bg-warning-subtle px-6 py-5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-warning/20 text-warning">
            <UserCheck className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1 pr-8">
            <h2 id="assign-agent-title" className="text-lg font-semibold">
              Connect with a Claim Expert
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              Get personalized help preparing a stronger claim before insurer submission.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 rounded-lg p-1.5 text-muted-foreground hover:bg-muted"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {!useCustomName && agents.length > 0 ? (
            <FormField label="Registered agent" htmlFor="agent-select">
              <Select
                id="agent-select"
                value={selectedAgentId}
                onChange={(e) => setSelectedAgentId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Select an agent...</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.full_name} ({agent.email})
                  </option>
                ))}
              </Select>
            </FormField>
          ) : (
            <FormField label="Agent name or email" htmlFor="agent-name">
              <Input
                id="agent-name"
                type="text"
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                placeholder="Jane Smith or jane@insurer.com"
                autoFocus
              />
            </FormField>
          )}

          {agents.length > 0 && (
            <button
              type="button"
              className="text-xs text-[#F96702] hover:underline"
              onClick={() => setUseCustomName(!useCustomName)}
            >
              {useCustomName ? "Choose from registered agents" : "Enter custom name instead"}
            </button>
          )}

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end pt-4 border-t">
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Assigning..." : "Assign Agent"}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

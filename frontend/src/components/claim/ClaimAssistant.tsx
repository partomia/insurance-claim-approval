import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, apiJson } from "@/lib/api";
import { AssistantMessage } from "@/components/assistant/AssistantMessage";

interface Message {
  role: string;
  content: string;
  local?: boolean;
}

interface EvidenceIssue {
  field: string;
  document_id: number;
  filename: string;
  reason: string;
  issue_code: string;
  acknowledged: boolean;
}

interface ClaimAssistantProps {
  claimId: string;
  variant?: "sidebar" | "dock";
  status?: string;
  escalationMessages?: string[];
  assignedAgent?: string | null;
  evidenceIssues?: EvidenceIssue[];
  evidenceMismatch?: boolean;
  onAssign?: () => void;
  onReplaceDocument?: (documentId: number) => void;
}

function buildProactiveOpener(
  messages: string[],
  assignedAgent?: string | null,
  evidenceIssues?: EvidenceIssue[]
): string {
  const unackedGov = evidenceIssues?.find(
    (i) => !i.acknowledged && i.field.toLowerCase().includes("government")
  );
  if (unackedGov) {
    return (
      `It looks like the Government ID you uploaded (${unackedGov.filename}) may not be a valid identity document. ` +
      "Would you like to upload a replacement now?"
    );
  }

  const flagText = messages.length > 0 ? messages.join("; ") : "risk indicators";
  const assignmentNote = assignedAgent
    ? ` Claim Expert ${assignedAgent} is helping you with this claim.`
    : " A Claim Expert can help you strengthen this before submission.";
  return (
    `This claim needs attention: ${flagText}.${assignmentNote} ` +
    "Would you like me to connect you with a Claim Expert now?"
  );
}

export function ClaimAssistant({
  claimId,
  variant = "dock",
  status,
  escalationMessages = [],
  assignedAgent,
  evidenceIssues = [],
  evidenceMismatch = false,
  onAssign,
  onReplaceDocument,
}: ClaimAssistantProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [proactiveShown, setProactiveShown] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const isPendingReview = status?.toUpperCase() === "PENDING_REVIEW";
  const unackedGovIssue = evidenceIssues.find(
    (i) => !i.acknowledged && i.field.toLowerCase().includes("government")
  );

  useEffect(() => {
    apiJson<Message[]>(`/api/claims/${claimId}/chat`)
      .then((data) => setMessages(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, [claimId]);

  useEffect(() => {
    const hasOpenerContext =
      escalationMessages.length > 0 || (evidenceMismatch && unackedGovIssue);
    if (isPendingReview && !proactiveShown && messages.length === 0 && hasOpenerContext) {
      setMessages([
        {
          role: "assistant",
          content: buildProactiveOpener(escalationMessages, assignedAgent, evidenceIssues),
          local: true,
        },
      ]);
      setProactiveShown(true);
    }
  }, [
    isPendingReview,
    proactiveShown,
    messages.length,
    escalationMessages,
    assignedAgent,
    evidenceIssues,
    evidenceMismatch,
    unackedGovIssue,
  ]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text?: string) => {
    const userMsg = (text ?? input).trim();
    if (!userMsg || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const res = await apiFetch(
        `/api/claims/${claimId}/chat`,
        {
          method: "POST",
          body: JSON.stringify({ message: userMsg }),
        },
        { json: true }
      );
      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [...prev, { role: "assistant", content: data.content }]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const isDock = variant === "dock";
  const messageAreaClass = isDock
    ? "max-h-[400px] overflow-y-auto px-4 py-3 space-y-3 bg-muted/30"
    : "flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3 bg-muted/30";

  return (
    <div className={isDock ? "flex flex-col" : "flex flex-col h-full min-h-0"}>
      <div className={messageAreaClass}>
        {messages.length === 0 && !isPendingReview && (
          <p className="text-sm text-muted-foreground px-1">
            Ask about your policy coverage, claim status, or required documents.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm p-3 rounded-lg ${isDock ? "max-w-3xl" : "max-w-[95%]"} ${
              m.role === "user"
                ? "bg-primary/10 border border-primary/20 ml-auto"
                : "bg-card border mr-auto"
            }`}
          >
            {m.role === "assistant" ? (
              <AssistantMessage content={m.content} />
            ) : (
              <p className="leading-relaxed whitespace-pre-wrap">{m.content}</p>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-sm text-muted-foreground p-3 bg-card border rounded-lg mr-auto max-w-3xl">
            Thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {isPendingReview && (
        <div className="flex flex-wrap gap-2 border-t bg-warning-subtle px-4 py-2">
          {unackedGovIssue && onReplaceDocument && (
            <Button
              type="button"
              variant="default"
              size="sm"
              onClick={() => onReplaceDocument(unackedGovIssue.document_id)}
            >
              Upload replacement
            </Button>
          )}
          {!assignedAgent && onAssign && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onAssign}
              className="border-warning-border text-warning hover:bg-warning/10"
            >
              Escalate to human agent now
            </Button>
          )}
        </div>
      )}

      <div className={`shrink-0 border-t bg-card p-4 ${isDock ? "" : "p-3"}`}>
        <div className={`flex gap-3 ${isDock ? "max-w-full" : ""}`}>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about policy coverage, payout, or claim status"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            disabled={loading}
            rows={2}
            className="assistant-input min-h-[56px] resize-none flex-1 w-full"
          />
          <Button onClick={() => send()} disabled={loading || !input.trim()} className="self-end px-6 shrink-0">
            {loading ? "..." : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}

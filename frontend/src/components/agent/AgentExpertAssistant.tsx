import { useEffect, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { agentApiFetch, agentApiJson } from "@/lib/agentApi";
import { AssistantMessage } from "@/components/assistant/AssistantMessage";
import { AssistantPanelShell } from "@/components/assistant/AssistantPanelShell";
import { Bot } from "lucide-react";

interface Message {
  role: string;
  content: string;
}

const STARTER_PROMPTS = [
  "What is this claim about?",
  "Summarize supporting documents",
  "Customer risk profile",
  "Missing requirements for review",
  "Policy coverage for this claim",
];

export function AgentExpertAssistant() {
  const location = useLocation();
  const params = useParams();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const claimId = location.pathname.startsWith("/agent/claims/") && params.id ? Number(params.id) : undefined;
  const customerId = location.pathname.startsWith("/agent/customers/") && params.id ? Number(params.id) : undefined;

  useEffect(() => {
    if (!open) return;
    agentApiJson<Message[]>("/api/agent/assistant/chat")
      .then((data) => setMessages(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

  const send = async (text?: string) => {
    const userMsg = (text ?? input).trim();
    if (!userMsg || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const res = await agentApiFetch(
        "/api/agent/assistant/chat",
        {
          method: "POST",
          body: JSON.stringify({
            message: userMsg,
            claim_id: claimId,
            customer_id: customerId,
          }),
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

  const subtitle = claimId
    ? `Claim review #${claimId}`
    : customerId
      ? `Customer #${customerId}`
      : "Assigned queue assistant";

  return (
    <AssistantPanelShell
      open={open}
      onOpenChange={setOpen}
      storageKey="claimcopilot:assistant-panel:expert"
      title="Expert Copilot"
      subtitle={subtitle}
      headerClassName="bg-secondary"
      panelClassName="border-2 border-secondary/50"
      fab={
        <span className="flex h-14 w-14 items-center justify-center rounded-full border-[3px] border-background bg-secondary text-secondary-foreground shadow-lg">
          <Bot className="h-6 w-6" />
        </span>
      }
      footer={
        <div className="border-t bg-background p-3 space-y-2">
          <Textarea
            className="assistant-input min-h-[72px] resize-none text-sm"
            placeholder="Ask about review steps, documents, customer risk, or policy..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button type="button" className="w-full bg-secondary text-secondary-foreground hover:bg-secondary/90" disabled={loading || !input.trim()} onClick={() => send()}>
            Send
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {messages.length === 0 && !loading && (
          <div className="space-y-3 px-1">
            <p className="rounded-xl border bg-card px-3 py-2.5 text-sm shadow-sm">
              Internal assistant for claim experts — summarize cases, review documents, assess risk, and plan next actions.
            </p>
            <div className="flex flex-col gap-2">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => send(prompt)}
                  className="assistant-prompt-btn text-left text-xs rounded-xl px-3 py-2.5 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm rounded-xl max-w-[92%] clear-both ${
              m.role === "user"
                ? "assistant-msg-user ml-auto mb-1 px-3.5 py-3"
                : "assistant-msg-bot mr-auto mb-1 px-3.5 py-3"
            }`}
          >
            {m.role === "assistant" ? <AssistantMessage content={m.content} /> : <p className="leading-relaxed whitespace-pre-wrap">{m.content}</p>}
          </div>
        ))}
        {loading && <p className="text-xs text-muted-foreground px-2">Expert Copilot is thinking...</p>}
        <div ref={bottomRef} />
      </div>
    </AssistantPanelShell>
  );
}

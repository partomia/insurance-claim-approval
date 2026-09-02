import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, apiJson } from "@/lib/api";
import { AssistantMessage } from "@/components/assistant/AssistantMessage";
import { AssistantPanelShell } from "@/components/assistant/AssistantPanelShell";
import { Sparkles } from "lucide-react";

interface Message {
  role: string;
  content: string;
}

const STARTER_PROMPTS = [
  "What's my motor claim approval chance?",
  "What documents do I need for this accident?",
  "Explain my compulsory excess and NCB impact",
];

export const OPEN_ASSISTANT_EVENT = "claimcopilot:open-assistant";

export function UniversalAssistant() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const claimId =
    location.pathname.startsWith("/analysis/") || location.pathname.startsWith("/track/")
      ? params.id
        ? Number(params.id)
        : undefined
      : undefined;

  useEffect(() => {
    if (!open) return;
    apiJson<Message[]>("/api/assistant/chat")
      .then((data) => setMessages(Array.isArray(data) ? data : []))
      .catch(console.error);
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

  const closeAssistant = () => {
    setOpen(false);
    if (location.hash === "#assistant") {
      navigate({ pathname: location.pathname, search: location.search }, { replace: true });
    }
  };

  useEffect(() => {
    if (location.hash === "#assistant") {
      setOpen(true);
    }
  }, [location.hash]);

  useEffect(() => {
    const handleOpen = (event: Event) => {
      setOpen(true);
      const prompt = (event as CustomEvent<{ prompt?: string }>).detail?.prompt;
      if (prompt) {
        setInput(`Help me with this next step: ${prompt}`);
      }
    };
    window.addEventListener(OPEN_ASSISTANT_EVENT, handleOpen);
    return () => window.removeEventListener(OPEN_ASSISTANT_EVENT, handleOpen);
  }, []);

  const send = async (text?: string) => {
    const userMsg = (text ?? input).trim();
    if (!userMsg || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const res = await apiFetch(
        "/api/assistant/chat",
        {
          method: "POST",
          body: JSON.stringify({
            message: userMsg,
            claim_id: claimId,
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

  return (
    <AssistantPanelShell
      open={open}
      onOpenChange={(next) => (next ? setOpen(true) : closeAssistant())}
      storageKey="claimcopilot:assistant-panel:customer"
      title="Motor Claim Copilot"
      subtitle={claimId ? `Helping with motor claim #${claimId}` : "Motor policy & claims assistant"}
      onBackdropClick={closeAssistant}
      fab={
        <span className="flex h-14 w-14 items-center justify-center rounded-full border-[3px] border-white bg-primary text-primary-foreground shadow-[0_8px_28px_rgba(249,103,2,0.55)]">
          <Sparkles className="h-6 w-6" />
        </span>
      }
      footer={
        <div className="shrink-0 p-3">
          <div className="flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about coverage, documents, or your policy..."
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              disabled={loading}
              rows={2}
              className="assistant-input min-h-[56px] resize-none flex-1"
            />
            <Button
              onClick={() => send()}
              disabled={loading || !input.trim()}
              className="self-end shrink-0 h-10 px-5 font-semibold shadow-md"
            >
              Send
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-3">
        {messages.length === 0 && !loading && (
          <div className="space-y-3 px-1">
            <p className="rounded-xl border bg-card px-3 py-2.5 text-sm shadow-sm">
              I can help with coverage, claim prep, and policy terms using your uploaded schedules.
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
            {m.role === "assistant" ? (
              <AssistantMessage content={m.content} />
            ) : (
              <p className="leading-relaxed whitespace-pre-wrap">{m.content}</p>
            )}
          </div>
        ))}
        {loading && (
          <div className="assistant-msg-bot text-sm text-muted-foreground px-3.5 py-3 rounded-xl mr-auto max-w-[92%]">
            Thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </AssistantPanelShell>
  );
}

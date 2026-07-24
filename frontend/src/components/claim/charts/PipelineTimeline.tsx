import { Check, Circle, Loader2 } from "lucide-react";

export interface TimelineEvent {
  step: string;
  label?: string;
  status?: string;
  message?: string;
  at?: string;
  timestamp?: string;
  run_id?: number;
  data?: { from_step?: string };
}

export const PIPELINE_STEPS = [
  "claim_submitted",
  "policy_validation",
  "rag_retrieval",
  "customer_profile",
  "evidence_analysis",
  "fraud_detection",
  "decision_engine",
  "payout_calculation",
  "completed",
] as const;

export const PIPELINE_STEP_LABELS: Record<string, string> = {
  claim_submitted: "Claim received",
  policy_validation: "Checking your policy",
  rag_retrieval: "Reviewing policy terms",
  customer_profile: "Verifying your details",
  evidence_analysis: "Reviewing your documents",
  fraud_detection: "Safety checks",
  decision_engine: "Assessing your claim",
  payout_calculation: "Calculating payout",
  completed: "Review complete",
  pipeline_reset: "Rechecking documents",
};

function stepLabel(step: string, event?: TimelineEvent): string {
  return PIPELINE_STEP_LABELS[step] || event?.label || step.replace(/_/g, " ");
}

const RESET_FROM_STEP = "evidence_analysis";
const RESET_FROM_INDEX = PIPELINE_STEPS.indexOf(RESET_FROM_STEP);

function eventTime(event: TimelineEvent): number {
  const iso = event.timestamp || event.at;
  if (!iso) return 0;
  return new Date(iso).getTime();
}

export function findPipelineReset(events: TimelineEvent[]): {
  resetAt: number;
  runId?: number;
} | null {
  const resets = events.filter(
    (e) =>
      e.step === "pipeline_reset" &&
      (e.data?.from_step === RESET_FROM_STEP || e.message?.includes("documents"))
  );
  if (resets.length === 0) return null;
  const latest = resets[resets.length - 1];
  return {
    resetAt: eventTime(latest),
    runId: latest.run_id,
  };
}

export function eventsForStep(step: string, allEvents: TimelineEvent[]): TimelineEvent[] {
  const reset = findPipelineReset(allEvents);
  const stepIndex = PIPELINE_STEPS.indexOf(step as (typeof PIPELINE_STEPS)[number]);

  const filtered = allEvents.filter((e) => e.step !== "pipeline_reset");

  if (!reset || stepIndex < RESET_FROM_INDEX) {
    return filtered.filter((e) => e.step === step);
  }

  return filtered.filter((e) => {
    if (e.step !== step) return false;
    const t = eventTime(e);
    if (reset.runId != null && e.run_id != null) {
      return e.run_id >= reset.runId;
    }
    return t >= reset.resetAt;
  });
}

export function stepState(step: string, events: TimelineEvent[]): "pending" | "running" | "completed" | "failed" {
  const match = eventsForStep(step, events);
  if (match.some((e) => e.status === "failed")) return "failed";
  if (match.some((e) => e.status === "completed")) return "completed";
  if (match.some((e) => e.status === "running")) return "running";
  if (match.length > 0) return "completed";
  return "pending";
}

function formatTime(iso?: string): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return null;
  }
}

function StepIcon({ state }: { state: "pending" | "running" | "completed" | "failed" }) {
  if (state === "completed") {
    return (
      <div className="w-8 h-8 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center shrink-0">
        <Check className="w-4 h-4 text-green-600" />
      </div>
    );
  }
  if (state === "failed") {
    return (
      <div className="w-8 h-8 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center shrink-0">
        <Circle className="w-3 h-3 text-red-600 fill-red-600" />
      </div>
    );
  }
  if (state === "running") {
    return (
      <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center shrink-0 animate-pulse">
        <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
      </div>
    );
  }
  return (
    <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center shrink-0">
      <Circle className="w-3 h-3 text-muted-foreground" />
    </div>
  );
}

export function PipelineTimeline({
  events,
  timeline,
  resetFromStep,
}: {
  events: TimelineEvent[];
  timeline?: TimelineEvent[];
  resetFromStep?: string;
}) {
  const merged = [...(timeline || []), ...events];
  const reset = findPipelineReset(merged);
  const showResetBanner = reset && (resetFromStep === RESET_FROM_STEP || reset != null);

  return (
    <>
      {showResetBanner && (
        <p className="text-xs text-blue-600 dark:text-blue-400 mb-3 font-medium">
          Rechecking your documents…
        </p>
      )}

      {/* Horizontal timeline — md+ */}
      <div className="hidden md:block overflow-x-auto pb-2">
        <div className="flex items-start min-w-max gap-0">
          {PIPELINE_STEPS.map((step, index) => {
            const state = stepState(step, merged);
            const stepEvents = eventsForStep(step, merged);
            const latest = stepEvents[stepEvents.length - 1];
            const time = formatTime(latest?.at || latest?.timestamp);

            return (
              <div key={step} className="flex items-start">
                <div className="flex flex-col items-center w-[100px]">
                  <StepIcon state={state} />
                  <p className={`text-[10px] text-center mt-1.5 leading-tight px-1 ${state === "pending" ? "text-muted-foreground" : "font-medium"}`}>
                    {stepLabel(step, latest)}
                  </p>
                  {time && (
                    <p className="text-[9px] text-muted-foreground mt-0.5">{time}</p>
                  )}
                </div>
                {index < PIPELINE_STEPS.length - 1 && (
                  <div
                    className={`h-0.5 w-6 mt-4 shrink-0 ${
                      state === "completed" ? "bg-green-400" : "bg-border"
                    }`}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Vertical timeline — mobile */}
      <div className="md:hidden space-y-0">
        {PIPELINE_STEPS.map((step, index) => {
          const state = stepState(step, merged);
          const stepEvents = eventsForStep(step, merged);
          const latest = stepEvents[stepEvents.length - 1];
          const time = formatTime(latest?.at || latest?.timestamp);

          return (
            <div key={step} className="flex gap-3">
              <div className="flex flex-col items-center">
                <StepIcon state={state} />
                {index < PIPELINE_STEPS.length - 1 && (
                  <div className={`w-0.5 flex-1 min-h-[20px] ${state === "completed" ? "bg-green-400" : "bg-border"}`} />
                )}
              </div>
              <div className="pb-4 min-w-0 flex-1">
                <p className={`text-sm ${state === "pending" ? "text-muted-foreground" : "font-medium"}`}>
                  {stepLabel(step, latest)}
                </p>
                {latest?.message && (
                  <p className="text-xs text-muted-foreground mt-0.5 truncate">{latest.message}</p>
                )}
                {time && <p className="text-[10px] text-muted-foreground mt-0.5">{time}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

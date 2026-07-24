import { FileWarning, MessageSquareQuote, ShieldCheck, Upload } from "lucide-react";

export interface ExpertRequestedDocument {
  id: string;
  label: string;
  document_type: string;
  fulfilled?: boolean;
}

export interface ExpertReview {
  expert_name: string;
  message: string;
  action?: string | null;
  action_label?: string | null;
  updated_at?: string | null;
  requested_documents?: ExpertRequestedDocument[];
}

function formatRelativeTime(iso?: string | null): string | null {
  if (!iso) return null;
  try {
    const date = new Date(iso);
    const diffMs = Date.now() - date.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return date.toLocaleDateString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch {
    return null;
  }
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

const ACTION_CONFIG: Record<
  string,
  { label: string; icon: typeof Upload; accent: string; badge: string }
> = {
  NEEDS_IMPROVEMENT: {
    label: "Documents needed",
    icon: Upload,
    accent: "border-l-warning",
    badge: "bg-warning text-warning-foreground border-warning",
  },
  SUBMISSION_READY: {
    label: "Ready for insurer",
    icon: ShieldCheck,
    accent: "border-l-success",
    badge: "bg-success text-success-foreground border-success",
  },
  CONTINUE_REVIEW: {
    label: "Under review",
    icon: MessageSquareQuote,
    accent: "border-l-secondary",
    badge: "bg-secondary text-secondary-foreground border-secondary",
  },
};

export function ExpertReviewCard({
  review,
  assignedAt,
  variant = "sidebar",
}: {
  review: ExpertReview;
  assignedAt?: string | null;
  variant?: "sidebar" | "inline";
}) {
  const actionKey = review.action ?? "";
  const config =
    ACTION_CONFIG[actionKey] ??
    ({
      label: review.action_label ?? "Expert update",
      icon: MessageSquareQuote,
      accent: "border-l-secondary",
      badge: "bg-secondary text-secondary-foreground border-secondary",
    } as const);

  const Icon = config.icon;
  const updated = formatRelativeTime(review.updated_at) ?? formatRelativeTime(assignedAt);
  const isDefaultMessage = review.message.startsWith("Hi — I'm");

  return (
    <section
      className={`rounded-xl border border-l-4 bg-card shadow-sm ${config.accent} ${
        variant === "sidebar" ? "lg:sticky lg:top-20" : ""
      }`}
    >
      <div className="p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground text-sm font-bold">
            {initials(review.expert_name)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
              Claim expert
            </p>
            <p className="text-base font-semibold">{review.expert_name}</p>
            {updated && <p className="mt-0.5 text-xs text-muted-foreground">Updated {updated}</p>}
          </div>
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${config.badge}`}
          >
            <Icon className="h-3 w-3" />
            {config.label}
          </span>
        </div>

        <div className="rounded-lg border bg-muted/40 p-4">
          {!isDefaultMessage ? (
            <>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
                Expert message
              </p>
              <p className="text-sm font-medium leading-relaxed">{review.message}</p>
            </>
          ) : (
            <p className="text-sm leading-relaxed text-muted-foreground">{review.message}</p>
          )}
        </div>

        {actionKey === "NEEDS_IMPROVEMENT" && !isDefaultMessage && (
          <div className="flex items-start gap-2.5 rounded-lg border border-warning-border bg-warning-subtle px-3 py-3">
            <FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <p className="text-xs font-medium leading-relaxed">
              {(review.requested_documents?.length ?? 0) > 0
                ? "Use the upload section below to submit each requested document."
                : "Upload the requested documents on the Track Claim page to continue review."}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

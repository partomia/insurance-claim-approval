const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  APPROVED: {
    label: "Approved",
    className: "bg-success text-success-foreground border-success",
  },
  REJECTED: {
    label: "Rejected",
    className: "bg-destructive text-white border-destructive",
  },
  ANALYSIS_COMPLETE: {
    label: "Analysis complete",
    className: "bg-info text-info-foreground border-info",
  },
  REQUEST_MORE_INFO: {
    label: "Action needed",
    className: "bg-warning text-warning-foreground border-warning",
  },
  PENDING_REVIEW: {
    label: "Expert review",
    className: "bg-secondary text-secondary-foreground border-secondary",
  },
  SUBMISSION_READY: {
    label: "Ready to submit",
    className: "bg-success text-success-foreground border-success",
  },
  SUBMITTED_TO_INSURER: {
    label: "Submitted to insurer",
    className: "bg-secondary text-secondary-foreground border-secondary",
  },
  HUMAN_REVIEW: {
    label: "Expert review",
    className: "bg-secondary text-secondary-foreground border-secondary",
  },
  PROCESSING: {
    label: "Processing",
    className: "bg-info text-info-foreground border-info",
  },
};

export function ClaimStatusBadge({
  status,
  assignedAgent,
  showExpert = true,
}: {
  status: string;
  assignedAgent?: string | null;
  showExpert?: boolean;
}) {
  const s = status.toUpperCase();
  const config = STATUS_CONFIG[s] ?? {
    label: status.replace(/_/g, " "),
    className: "bg-muted text-foreground border-border",
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={`inline-flex items-center rounded-md border px-3 py-1 text-xs font-bold uppercase tracking-wide ${config.className}`}
      >
        {config.label}
      </span>
      {showExpert && assignedAgent && (
        <span className="text-xs font-medium text-muted-foreground">{assignedAgent}</span>
      )}
    </div>
  );
}

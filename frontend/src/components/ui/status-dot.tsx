import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

type StatusTone = "success" | "pending" | "danger" | "info";

interface StatusDotProps extends React.ComponentProps<"span"> {
  tone?: StatusTone;
  done?: boolean;
  size?: "sm" | "md";
}

const TONE_STYLES: Record<StatusTone, string> = {
  success: "bg-success text-success-foreground border-success",
  pending: "bg-transparent text-muted-foreground border-border",
  danger: "bg-destructive/10 text-destructive border-destructive/40",
  info: "bg-info/15 text-info border-info/50",
};

/**
 * Small circular status indicator.
 * When `done` is true, tone becomes "success" and a check icon is rendered.
 */
export function StatusDot({
  tone = "pending",
  done,
  size = "md",
  className,
  ...props
}: StatusDotProps) {
  const effectiveTone = done ? "success" : tone;
  const dim = size === "sm" ? "h-4 w-4" : "h-5 w-5";
  const iconSize = size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5";
  return (
    <span
      role="img"
      aria-label={done ? "Completed" : "Pending"}
      className={cn(
        "inline-flex items-center justify-center rounded-full border shrink-0",
        dim,
        TONE_STYLES[effectiveTone],
        className,
      )}
      {...props}
    >
      {done && <Check className={iconSize} strokeWidth={3} />}
    </span>
  );
}

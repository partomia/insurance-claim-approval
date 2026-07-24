import * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Tone = "default" | "success" | "warning" | "danger" | "info";

const TONE_CARD: Record<Tone, string> = {
  default: "",
  success: "ring-success-border",
  warning: "ring-warning-border",
  danger: "ring-destructive/40",
  info: "ring-info-border",
};

const TONE_ICON: Record<Tone, string> = {
  default: "text-muted-foreground/60",
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
  info: "text-info",
};

interface StatCardProps {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: Tone;
  className?: string;
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "default",
  className,
}: StatCardProps) {
  return (
    <Card className={cn("shadow-sm", TONE_CARD[tone], className)}>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className="text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
              {value}
            </p>
            {hint && (
              <p className="text-xs text-muted-foreground">{hint}</p>
            )}
          </div>
          {icon && (
            <span
              aria-hidden
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-lg bg-muted/60",
                TONE_ICON[tone],
              )}
            >
              {icon}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

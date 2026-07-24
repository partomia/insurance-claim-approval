import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface BackLink {
  to: string;
  label: string;
}

interface Meta {
  label: string;
  value: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "info";
}

interface DetailHeaderProps {
  back?: BackLink;
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  status?: ReactNode;
  /** Right-aligned action buttons. */
  actions?: ReactNode;
  /** Optional row of key/value meta rendered under the title. */
  meta?: Meta[];
  className?: string;
}

const TONE_TEXT: Record<NonNullable<Meta["tone"]>, string> = {
  default: "text-foreground",
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
  info: "text-info",
};

/**
 * Shared detail-page header used by every claim / audit / review page across
 * all three portals. Renders a back link, title, status, optional meta row,
 * and right-aligned actions — all with consistent spacing and typography.
 */
export function DetailHeader({
  back,
  eyebrow,
  title,
  subtitle,
  status,
  actions,
  meta,
  className,
}: DetailHeaderProps) {
  return (
    <Card className={cn("shadow-sm", className)}>
      <CardContent className="pt-5 pb-5">
        {back && (
          <Link
            to={back.to}
            className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {back.label}
          </Link>
        )}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1.5">
            {eyebrow && (
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {eyebrow}
              </p>
            )}
            <h1 className="truncate text-2xl font-semibold tracking-tight sm:text-3xl">
              {title}
            </h1>
            {subtitle && (
              <p className="text-sm text-muted-foreground sm:text-[0.95rem]">{subtitle}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            {status}
            {actions}
          </div>
        </div>
        {meta && meta.length > 0 && (
          <dl className="mt-4 grid gap-x-6 gap-y-2 border-t pt-4 sm:grid-cols-2 lg:grid-cols-4">
            {meta.map((item, i) => (
              <div key={i} className="min-w-0">
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {item.label}
                </dt>
                <dd
                  className={cn(
                    "mt-0.5 truncate text-sm font-medium",
                    TONE_TEXT[item.tone ?? "default"],
                  )}
                >
                  {item.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

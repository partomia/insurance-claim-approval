import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionHeadingProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

/**
 * Consistent H2 used above a section of content on a detail page.
 * Kept intentionally minimal — for card interiors, keep using CardHeader/CardTitle.
 */
export function SectionHeading({
  icon,
  title,
  description,
  actions,
  className,
}: SectionHeadingProps) {
  return (
    <div className={cn("flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-0.5">
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          {icon}
          {title}
        </h2>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

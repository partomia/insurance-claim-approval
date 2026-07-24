import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Solid, low-contrast placeholder block used while data is loading.
 * Prefer this over ad-hoc `bg-muted animate-pulse` divs.
 */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      className={cn("animate-pulse rounded-md bg-muted/60", className)}
      {...props}
    />
  );
}

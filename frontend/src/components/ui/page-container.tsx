import * as React from "react";
import { cn } from "@/lib/utils";

type Size = "sm" | "md" | "lg" | "xl";

const SIZE: Record<Size, string> = {
  sm: "max-w-2xl",
  md: "max-w-3xl",
  lg: "max-w-5xl",
  xl: "max-w-7xl",
};

interface PageContainerProps extends React.ComponentProps<"div"> {
  size?: Size;
}

/**
 * Consistent page-width wrapper. The Layout `<main>` already provides
 * horizontal padding, so we only constrain width and stack children.
 */
export function PageContainer({
  size = "xl",
  className,
  ...props
}: PageContainerProps) {
  return (
    <div
      className={cn("mx-auto w-full space-y-8", SIZE[size], className)}
      {...props}
    />
  );
}

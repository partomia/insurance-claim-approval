import type { ReactNode } from "react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

interface AuthShellProps {
  /** Small text above the title, e.g. "Customer sign-in". */
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  /** Icon rendered inside the branded badge above the title. */
  icon: ReactNode;
  /** Optional badge tint override; defaults to primary. */
  iconClassName?: string;
  children: ReactNode;
  footer?: ReactNode;
}

/**
 * One consistent layout for every role's auth page.
 * Role branding varies via `icon` + `iconClassName`; type/spacing/scale don't.
 */
export function AuthShell({
  eyebrow,
  title,
  description,
  icon,
  iconClassName,
  children,
  footer,
}: AuthShellProps) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface p-4">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-3">
          <span
            className={`inline-flex h-10 w-10 items-center justify-center rounded-lg text-primary-foreground ${
              iconClassName ?? "bg-primary"
            }`}
          >
            {icon}
          </span>
          {eyebrow && (
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {eyebrow}
            </p>
          )}
          <CardTitle className="text-2xl font-semibold tracking-tight">
            {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent>{children}</CardContent>
        {footer && <CardFooter className="flex flex-col gap-3">{footer}</CardFooter>}
      </Card>
    </div>
  );
}

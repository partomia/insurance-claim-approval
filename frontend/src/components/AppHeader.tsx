import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";

export interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

interface AppHeaderProps {
  brand: {
    to: string;
    label: string;
    icon: ReactNode;
    /** Tailwind classes for the icon badge (e.g. bg color). */
    iconClassName?: string;
  };
  nav: NavItem[];
  actions?: ReactNode;
}

/**
 * Shared top navigation. Renders active state via `aria-current` +
 * a visible accent bar, provides a persistent theme toggle, and
 * exposes a compact mobile drawer for the primary nav.
 */
export function AppHeader({ brand, nav, actions }: AppHeaderProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur-md">
      <div className="container mx-auto flex h-14 items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link
            to={brand.to}
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <span
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-lg text-primary-foreground",
                brand.iconClassName ?? "bg-primary",
              )}
            >
              {brand.icon}
            </span>
            <span className="text-[0.95rem]">{brand.label}</span>
          </Link>

          <nav className="hidden items-center gap-0.5 md:flex" aria-label="Primary">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "relative rounded-md px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "text-foreground"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span>{item.label}</span>
                    {isActive && (
                      <span
                        aria-hidden
                        className="absolute inset-x-3 -bottom-[13px] h-[2px] rounded-full bg-primary"
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          {actions}
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((v) => !v)}
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {mobileOpen && (
        <div className="border-t bg-background md:hidden">
          <nav
            className="container mx-auto flex flex-col gap-1 px-2 py-2"
            aria-label="Mobile primary"
          >
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/10 text-foreground"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}

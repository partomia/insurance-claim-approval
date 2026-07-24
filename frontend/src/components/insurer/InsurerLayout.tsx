import { Outlet } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { insurerLogout } from "@/lib/insurerAuth";
import { AppHeader, type NavItem } from "@/components/AppHeader";
import { Building2 } from "lucide-react";

const nav: NavItem[] = [
  { to: "/insurer/dashboard", label: "Dashboard" },
  { to: "/insurer/claims", label: "Claims" },
];

export function InsurerLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-surface text-foreground">
      <AppHeader
        brand={{
          to: "/insurer/dashboard",
          label: "ClaimCopilot Insurer",
          icon: <Building2 className="h-4 w-4" />,
          iconClassName: "bg-secondary text-secondary-foreground",
        }}
        nav={nav}
        actions={
          <Button variant="outline" size="sm" onClick={() => insurerLogout()}>
            Logout
          </Button>
        }
      />
      <main className="container mx-auto flex-1 px-4 py-8 max-w-7xl">
        <Outlet />
      </main>
    </div>
  );
}

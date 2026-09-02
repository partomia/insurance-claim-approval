import { Outlet } from "react-router-dom";
import { Button } from "./ui/button";
import { logout } from "@/lib/auth";
import { Sparkles } from "lucide-react";
import { UniversalAssistant } from "@/components/assistant/UniversalAssistant";
import { AppHeader, type NavItem } from "@/components/AppHeader";

const nav: NavItem[] = [
  { to: "/dashboard", label: "Home" },
  { to: "/policies/connect", label: "Motor Policies" },
  { to: "/claim", label: "New Motor Claim" },
  { to: "/history", label: "My Motor Claims" },
  { to: "/profile", label: "Profile" },
];

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-surface text-foreground">
      <AppHeader
        brand={{
          to: "/dashboard",
          label: "Motor Claim Copilot",
          icon: <Sparkles className="h-4 w-4" />,
        }}
        nav={nav}
        actions={
          <Button variant="outline" size="sm" onClick={logout}>
            Logout
          </Button>
        }
      />
      <main className="container mx-auto flex-1 px-4 py-8 max-w-7xl">
        <Outlet />
      </main>
      <UniversalAssistant />
    </div>
  );
}

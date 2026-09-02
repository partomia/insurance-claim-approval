import { Outlet } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { agentLogout } from "@/lib/agentAuth";
import { AgentExpertAssistant } from "@/components/agent/AgentExpertAssistant";
import { AppHeader, type NavItem } from "@/components/AppHeader";
import { Users } from "lucide-react";

const nav: NavItem[] = [
  { to: "/agent/dashboard", label: "Motor Claims Workspace" },
  { to: "/agent/claims", label: "Motor Claims Queue" },
  { to: "/agent/profile", label: "Profile" },
];

export function AgentLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-surface text-foreground">
      <AppHeader
        brand={{
          to: "/agent/dashboard",
          label: "Motor Claim Copilot — Expert",
          icon: <Users className="h-4 w-4" />,
          iconClassName: "bg-secondary text-secondary-foreground",
        }}
        nav={nav}
        actions={
          <Button variant="outline" size="sm" onClick={() => agentLogout()}>
            Logout
          </Button>
        }
      />
      <main className="container mx-auto flex-1 px-4 py-8 max-w-7xl">
        <Outlet />
      </main>
      <AgentExpertAssistant />
    </div>
  );
}

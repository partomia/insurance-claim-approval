import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { getAgentToken, isAgentAuthenticated, refreshAgentSession } from "@/lib/agentAuth";

export function AgentProtectedRoute() {
  const location = useLocation();
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(isAgentAuthenticated());

  useEffect(() => {
    const init = async () => {
      if (getAgentToken()) {
        setAuthed(true);
        setReady(true);
        return;
      }
      if (isAgentAuthenticated()) {
        const ok = await refreshAgentSession();
        setAuthed(ok);
      } else {
        setAuthed(false);
      }
      setReady(true);
    };
    init();
  }, []);

  if (!ready) {
    return <div className="p-6 text-muted-foreground">Loading agent session...</div>;
  }

  if (!authed) {
    return (
      <Navigate
        to="/agent/auth"
        replace
        state={{ from: location }}
      />
    );
  }

  return <Outlet />;
}

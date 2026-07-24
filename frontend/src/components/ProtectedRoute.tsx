import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { getToken, isAuthenticated, refreshSession } from "@/lib/auth";

export function ProtectedRoute() {
  const location = useLocation();
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(isAuthenticated());

  useEffect(() => {
    const init = async () => {
      if (getToken()) {
        setAuthed(true);
        setReady(true);
        return;
      }
      if (isAuthenticated()) {
        const ok = await refreshSession();
        setAuthed(ok);
      } else {
        setAuthed(false);
      }
      setReady(true);
    };
    init();
  }, []);

  if (!ready) {
    return <div className="p-6 text-muted-foreground">Loading session...</div>;
  }

  if (!authed) {
    return (
      <Navigate
        to="/auth"
        replace
        state={{ from: location }}
      />
    );
  }

  return <Outlet />;
}

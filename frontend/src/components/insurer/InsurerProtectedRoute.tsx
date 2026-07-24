import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { getInsurerToken, isInsurerAuthenticated, refreshInsurerSession } from "@/lib/insurerAuth";

export function InsurerProtectedRoute() {
  const location = useLocation();
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(isInsurerAuthenticated());

  useEffect(() => {
    const init = async () => {
      if (getInsurerToken()) {
        setAuthed(true);
        setReady(true);
        return;
      }
      if (isInsurerAuthenticated()) {
        const ok = await refreshInsurerSession();
        setAuthed(ok);
      } else {
        setAuthed(false);
      }
      setReady(true);
    };
    init();
  }, []);

  if (!ready) {
    return <div className="p-6 text-muted-foreground">Loading insurer session...</div>;
  }

  if (!authed) {
    return (
      <Navigate
        to="/insurer/auth"
        replace
        state={{ from: location }}
      />
    );
  }

  return <Outlet />;
}

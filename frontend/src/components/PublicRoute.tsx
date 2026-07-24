import { Navigate, Outlet } from "react-router-dom";
import { isAuthenticated } from "@/lib/auth";

export function PublicRoute() {
  if (isAuthenticated()) {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}

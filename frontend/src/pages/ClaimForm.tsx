/**
 * Legacy single-shot claim form — superseded by the motor 4-step wizard
 * at /claim (frontend/src/pages/ClaimWizard.tsx). Kept only so any stale
 * bookmarks redirect cleanly. Do not add new logic here.
 */
import { Navigate } from "react-router-dom";

export function ClaimForm() {
  return <Navigate to="/claim" replace />;
}

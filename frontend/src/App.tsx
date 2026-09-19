import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { Auth } from "./pages/Auth";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { PublicRoute } from "./components/PublicRoute";
import { Dashboard } from "./pages/Dashboard";
import ClaimWizard from "./pages/ClaimWizard";
import { TrackClaim } from "./pages/TrackClaim";
import { History } from "./pages/History";
import { Profile } from "./pages/Profile";
import { AuditReport } from "./pages/AuditReport";
import { KYC } from "./pages/KYC";
import { ConnectPolicy } from "./pages/ConnectPolicy";
import { ClaimAnalysis } from "./pages/ClaimAnalysis";
import { isAuthenticated } from "./lib/auth";
import { isAgentAuthenticated } from "./lib/agentAuth";
import { isInsurerAuthenticated } from "./lib/insurerAuth";
import { AgentAuth } from "./pages/agent/AgentAuth";
import { AgentProtectedRoute } from "./components/agent/AgentProtectedRoute";
import { AgentLayout } from "./components/agent/AgentLayout";
import { AgentDashboard } from "./pages/agent/AgentDashboard";
import { AgentClaims } from "./pages/agent/AgentClaims";
import { AgentClaimReview } from "./pages/agent/AgentClaimReview";
import { AgentCustomer } from "./pages/agent/AgentCustomer";
import { AgentProfile } from "./pages/agent/AgentProfile";
import { AgentAuditReport } from "./pages/agent/AgentAuditReport";
import { InsurerAuth } from "./pages/insurer/InsurerAuth";
import { InsurerProtectedRoute } from "./components/insurer/InsurerProtectedRoute";
import { InsurerLayout } from "./components/insurer/InsurerLayout";
import { InsurerDashboard } from "./pages/insurer/InsurerDashboard";
import { InsurerClaims } from "./pages/insurer/InsurerClaims";
import { InsurerClaimReview } from "./pages/insurer/InsurerClaimReview";
import { InsurerAuditReport } from "./pages/insurer/InsurerAuditReport";
import { InsurerBookOfBusiness } from "./pages/insurer/InsurerBookOfBusiness";

function defaultHome() {
  if (isAuthenticated()) return "/dashboard";
  if (isAgentAuthenticated()) return "/agent/dashboard";
  if (isInsurerAuthenticated()) return "/insurer/dashboard";
  return "/auth";
}

function App() {
  return (
    <Router>
      <Routes>
        <Route element={<PublicRoute />}>
          <Route path="/auth" element={<Auth />} />
          <Route path="/agent/auth" element={<AgentAuth />} />
          <Route path="/insurer/auth" element={<InsurerAuth />} />
        </Route>

        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/kyc" element={<KYC />} />
            <Route path="/policies/connect" element={<ConnectPolicy />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/claim" element={<ClaimWizard />} />
            <Route path="/analysis/:id" element={<ClaimAnalysis />} />
            <Route path="/track/:id" element={<TrackClaim />} />
            <Route path="/audit/:id" element={<AuditReport />} />
            <Route path="/history" element={<History />} />
          </Route>
        </Route>

        <Route element={<AgentProtectedRoute />}>
          <Route element={<AgentLayout />}>
            <Route path="/agent/dashboard" element={<AgentDashboard />} />
            <Route path="/agent/claims" element={<AgentClaims />} />
            <Route path="/agent/claims/:id" element={<AgentClaimReview />} />
            <Route path="/agent/claims/:id/audit" element={<AgentAuditReport />} />
            <Route path="/agent/customers/:id" element={<AgentCustomer />} />
            <Route path="/agent/profile" element={<AgentProfile />} />
          </Route>
        </Route>

        <Route element={<InsurerProtectedRoute />}>
          <Route element={<InsurerLayout />}>
            <Route path="/insurer/dashboard" element={<InsurerDashboard />} />
            <Route path="/insurer/book-of-business" element={<InsurerBookOfBusiness />} />
            <Route path="/insurer/claims" element={<InsurerClaims />} />
            <Route path="/insurer/claims/:id" element={<InsurerClaimReview />} />
            <Route path="/insurer/claims/:id/audit" element={<InsurerAuditReport />} />
          </Route>
        </Route>

        <Route path="/" element={<Navigate to={defaultHome()} replace />} />
        <Route path="*" element={<Navigate to={defaultHome()} replace />} />
      </Routes>
    </Router>
  );
}

export default App;

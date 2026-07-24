import { useState } from "react";
import { Users } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/components/ui/auth-shell";
import { clearAgentTokens, setAgentTokens } from "@/lib/agentAuth";
import { apiUrl } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

export function AgentAuth() {
  const { success, error } = useToast();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("112233");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const getReturnPath = () => {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get("returnTo");
    const fromState = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;
    return fromQuery || fromState || "/agent/dashboard";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (otpSent) {
        const response = await fetch(apiUrl("/agent/auth/verify-otp"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, otp }),
        });
        if (response.ok) {
          const data = await response.json();
          setAgentTokens(data.access_token, data.refresh_token);
          navigate(getReturnPath(), { replace: true });
        } else {
          error("Invalid OTP");
        }
        return;
      }

      const endpoint = isLogin ? "/agent/auth/login" : "/agent/auth/signup";
      const body = isLogin
        ? { email, password }
        : { email, password, full_name: fullName, invite_code: inviteCode, department: department || undefined };

      const response = await fetch(apiUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (response.ok) {
        if (isLogin) {
          setOtpSent(true);
        } else {
          clearAgentTokens();
          success("Staff account created! Enter OTP to sign in.");
          const loginRes = await fetch(apiUrl("/agent/auth/login"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });
          setIsLogin(true);
          if (loginRes.ok) setOtpSent(true);
        }
      } else {
        const errorData = await response.json();
        error(formatApiError(errorData.detail));
      }
    } catch {
      error("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      eyebrow="Expert portal"
      title={otpSent ? "Verify OTP" : isLogin ? "Expert sign-in" : "Staff sign up"}
      description={
        otpSent
          ? "Enter the OTP sent to your email"
          : isLogin
            ? "Sign in to review assigned claims"
            : "Create a policy agent account with your invite code"
      }
      icon={<Users className="h-5 w-5" />}
      iconClassName="bg-secondary text-secondary-foreground"
      footer={
        !otpSent && (
          <>
            <div className="w-full text-center text-sm text-muted-foreground">
              {isLogin ? "Need an account? " : "Already registered? "}
              <button
                type="button"
                className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:underline"
                onClick={() => setIsLogin(!isLogin)}
              >
                {isLogin ? "Staff sign up" : "Sign in"}
              </button>
            </div>
            <div className="relative w-full">
              <div className="absolute inset-0 flex items-center" aria-hidden>
                <div className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-card px-2 uppercase tracking-wide text-muted-foreground">
                  Or sign in as
                </span>
              </div>
            </div>
            <div className="grid w-full grid-cols-2 gap-2">
              <Button type="button" variant="outline" onClick={() => navigate("/auth")}>
                Customer
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate("/insurer/auth")}>
                Insurer
              </Button>
            </div>
          </>
        )
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {!otpSent && !isLogin && (
          <>
            <div className="space-y-2">
              <Label htmlFor="fullName">Full name</Label>
              <Input
                id="fullName"
                placeholder="Alex Agent"
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="department">Department</Label>
              <Input
                id="department"
                placeholder="Claims Review"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="inviteCode">Invite code</Label>
              <Input
                id="inviteCode"
                placeholder="CLOUDERA2026"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                required
              />
            </div>
          </>
        )}
        {!otpSent && (
          <>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="agent@cloudera.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </>
        )}
        {otpSent && (
          <div className="space-y-2">
            <Label htmlFor="otp">OTP</Label>
            <Input
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">
              Demo OTP: <span className="font-mono">112233</span>
            </p>
          </div>
        )}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Please wait…" : otpSent ? "Verify & sign in" : isLogin ? "Continue" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  );
}

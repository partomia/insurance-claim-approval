import { useState } from "react";
import { Building2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/components/ui/auth-shell";
import { clearInsurerTokens, setInsurerTokens } from "@/lib/insurerAuth";
import { apiUrl } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

export function InsurerAuth() {
  const { error } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("112233");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const getReturnPath = () => {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get("returnTo");
    const fromState = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;
    return fromQuery || fromState || "/insurer/dashboard";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (otpSent) {
        const response = await fetch(apiUrl("/insurer/auth/verify-otp"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, otp }),
        });
        if (response.ok) {
          const data = await response.json();
          setInsurerTokens(data.access_token, data.refresh_token);
          navigate(getReturnPath(), { replace: true });
        } else {
          error("Invalid OTP");
        }
        return;
      }

      const response = await fetch(apiUrl("/insurer/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (response.ok) {
        setOtpSent(true);
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
      eyebrow="Insurer portal"
      title={otpSent ? "Verify OTP" : "Insurer sign-in"}
      description={
        otpSent
          ? "Enter the OTP sent to your email"
          : "Sign in to review claims submitted by customers and experts"
      }
      icon={<Building2 className="h-5 w-5" />}
      iconClassName="bg-secondary text-secondary-foreground"
      footer={
        !otpSent ? (
          <>
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
              <Button type="button" variant="outline" onClick={() => navigate("/agent/auth")}>
                Claim Expert
              </Button>
            </div>
          </>
        ) : (
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => {
              clearInsurerTokens();
              setOtpSent(false);
            }}
          >
            Back to login
          </Button>
        )
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {!otpSent && (
          <>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="insurer1@claimcopilot.in"
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
                autoComplete="current-password"
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
          {busy ? "Please wait…" : otpSent ? "Verify & sign in" : "Continue"}
        </Button>
      </form>
    </AuthShell>
  );
}

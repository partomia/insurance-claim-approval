import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/components/ui/auth-shell";
import { setTokens, clearTokens } from "@/lib/auth";
import { apiUrl } from "@/lib/api";
import { formatApiError, useToast } from "@/components/ui/toast";

export function Auth() {
  const { success, error } = useToast();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("112233");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const getReturnPath = () => {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get("returnTo");
    const fromState = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;
    return fromQuery || fromState || "/dashboard";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (otpSent) {
        const response = await fetch(apiUrl("/auth/verify-otp"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, otp }),
        });
        if (response.ok) {
          const data = await response.json();
          setTokens(data.access_token, data.refresh_token);
          navigate(getReturnPath(), { replace: true });
        } else {
          error("Invalid OTP");
        }
        return;
      }

      const endpoint = isLogin ? "/auth/login" : "/auth/signup";
      const body = isLogin
        ? { email, password }
        : { email, password, full_name: fullName };

      const response = await fetch(apiUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (response.ok) {
        if (isLogin) {
          setOtpSent(true);
        } else {
          clearTokens();
          success("Account created! Enter OTP to sign in.");
          const loginRes = await fetch(apiUrl("/auth/login"), {
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
      eyebrow="Customer portal"
      title={otpSent ? "Verify OTP" : isLogin ? "Welcome back" : "Create your account"}
      description={
        otpSent
          ? "Enter the OTP sent to your email"
          : isLogin
            ? "Enter your email and password to continue"
            : "Create a new account to submit claims"
      }
      icon={<Sparkles className="h-5 w-5" />}
      footer={
        !otpSent && (
          <>
            <div className="w-full text-center text-sm text-muted-foreground">
              {isLogin ? "Don't have an account? " : "Already have an account? "}
              <button
                type="button"
                className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:underline"
                onClick={() => setIsLogin(!isLogin)}
              >
                {isLogin ? "Sign up" : "Login"}
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
              <Button type="button" variant="outline" onClick={() => navigate("/agent/auth")}>
                Claim Expert
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
          <div className="space-y-2">
            <Label htmlFor="fullName">Full name</Label>
            <Input
              id="fullName"
              placeholder="John Doe"
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </div>
        )}
        {!otpSent && (
          <>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
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
          {busy ? "Please wait…" : otpSent ? "Verify" : isLogin ? "Login" : "Sign Up"}
        </Button>
      </form>
    </AuthShell>
  );
}

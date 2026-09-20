// Same-origin safe base: empty VITE_API_URL → relative paths against own origin.
const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "agent_token";
const REFRESH_KEY = "agent_refresh_token";
const AUTH_COOKIE_NAME = "app_agent_auth_token";

// See auth.ts's setAuthCookie() — same belt-and-suspenders mirror into a
// plain cookie, distinct name so it can't collide with the customer/insurer
// portals' cookies in the same browser (cookies auto-attach to every
// same-origin request, unlike our explicit per-request X-Auth-Token header).
function setAuthCookie(token: string): void {
  document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

function clearAuthCookie(): void {
  document.cookie = `${AUTH_COOKIE_NAME}=; path=/; SameSite=Lax; max-age=0`;
}

export function getAgentToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getAgentRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setAgentTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
  setAuthCookie(accessToken);
}

export function clearAgentTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  clearAuthCookie();
}

export function isAgentAuthenticated(): boolean {
  return Boolean(getAgentToken() || getAgentRefreshToken());
}

export function agentAuthHeaders(json = false): HeadersInit {
  const token = getAgentToken();
  const headers: Record<string, string> = {};
  if (token) {
    // See auth.ts authHeaders() — custom header avoids Istio's Authorization-
    // header JWT check on some Cloudera AI workspaces.
    headers["X-Auth-Token"] = token;
  }
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export function agentLogout(): void {
  const refresh = getAgentRefreshToken();
  if (refresh) {
    fetch(`${API_BASE}/agent/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => {});
  }
  clearAgentTokens();
  window.location.href = "/agent/auth";
}

export function redirectToAgentLogin(returnTo?: string): void {
  clearAgentTokens();
  const path = returnTo || window.location.pathname + window.location.search;
  const params = path && path !== "/agent/auth" ? `?returnTo=${encodeURIComponent(path)}` : "";
  window.location.href = `/agent/auth${params}`;
}

export async function refreshAgentSession(): Promise<boolean> {
  const refresh = getAgentRefreshToken();
  if (!refresh) return false;

  try {
    const res = await fetch(`${API_BASE}/agent/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      clearAgentTokens();
      return false;
    }
    const data = await res.json();
    setAgentTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clearAgentTokens();
    return false;
  }
}

// Same-origin safe base: empty VITE_API_URL → relative paths against own origin.
const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "agent_token";
const REFRESH_KEY = "agent_refresh_token";

export function getAgentToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getAgentRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setAgentTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
}

export function clearAgentTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isAgentAuthenticated(): boolean {
  return Boolean(getAgentToken() || getAgentRefreshToken());
}

export function agentAuthHeaders(json = false): HeadersInit {
  const token = getAgentToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
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

// Same-origin safe base: empty VITE_API_URL → relative paths against own origin.
const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "token";
const REFRESH_KEY = "refresh_token";
const AUTH_COOKIE_NAME = "app_auth_token";

// Mirrors the access token into a plain (JS-readable, non-HttpOnly) cookie
// in addition to the X-Auth-Token header set in authHeaders() below. Belt
// and suspenders against some Cloudera AI workspaces' Istio ingress, which
// silently 401s (before the request reaches our API) our own app-issued
// JWT wherever it looks for one — confirmed on the `Authorization` header;
// a plain cookie is essentially never inspected by that class of
// header-focused mesh policy. Browsers send same-origin cookies
// automatically, so no fetch()-call changes are needed to use it.
function setAuthCookie(token: string): void {
  document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

function clearAuthCookie(): void {
  document.cookie = `${AUTH_COOKIE_NAME}=; path=/; SameSite=Lax; max-age=0`;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
  setAuthCookie(accessToken);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  setAuthCookie(token);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  clearAuthCookie();
}

export function clearToken(): void {
  clearTokens();
}

export function isAuthenticated(): boolean {
  return Boolean(getToken() || getRefreshToken());
}

export function authHeaders(json = false): HeadersInit {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    // Sent as a custom header (not `Authorization`) because some Cloudera AI
    // workspaces front the app with an Istio ingress that runs its own JWT
    // check against the `Authorization` header and silently 401s anything
    // that isn't its own SSO-issued token — before it ever reaches our API.
    headers["X-Auth-Token"] = token;
  }
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export function logout(): void {
  const refresh = getRefreshToken();
  if (refresh) {
    fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => {});
  }
  clearTokens();
  window.location.href = "/auth";
}

export function redirectToLogin(returnTo?: string): void {
  clearTokens();
  const path = returnTo || window.location.pathname + window.location.search;
  const params = path && path !== "/auth" ? `?returnTo=${encodeURIComponent(path)}` : "";
  window.location.href = `/auth${params}`;
}

export async function refreshSession(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      clearTokens();
      return false;
    }
    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}

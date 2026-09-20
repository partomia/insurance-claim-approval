// Same-origin safe base: empty VITE_API_URL → relative paths against own origin.
const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "insurer_token";
const REFRESH_KEY = "insurer_refresh_token";
const AUTH_COOKIE_NAME = "app_insurer_auth_token";

// See auth.ts's setAuthCookie() — same belt-and-suspenders mirror into a
// plain cookie, distinct name so it can't collide with the customer/agent
// portals' cookies in the same browser (cookies auto-attach to every
// same-origin request, unlike our explicit per-request X-Auth-Token header).
function setAuthCookie(token: string): void {
  document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

function clearAuthCookie(): void {
  document.cookie = `${AUTH_COOKIE_NAME}=; path=/; SameSite=Lax; max-age=0`;
}

export function getInsurerToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getInsurerRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setInsurerTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
  setAuthCookie(accessToken);
}

export function clearInsurerTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  clearAuthCookie();
}

export function isInsurerAuthenticated(): boolean {
  return Boolean(getInsurerToken() || getInsurerRefreshToken());
}

export function insurerAuthHeaders(json = false): HeadersInit {
  const token = getInsurerToken();
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

export function insurerLogout(): void {
  const refresh = getInsurerRefreshToken();
  if (refresh) {
    fetch(`${API_BASE}/insurer/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => {});
  }
  clearInsurerTokens();
  window.location.href = "/insurer/auth";
}

export function redirectToInsurerLogin(returnTo?: string): void {
  clearInsurerTokens();
  const path = returnTo || window.location.pathname + window.location.search;
  const params = path && path !== "/insurer/auth" ? `?returnTo=${encodeURIComponent(path)}` : "";
  window.location.href = `/insurer/auth${params}`;
}

export async function refreshInsurerSession(): Promise<boolean> {
  const refresh = getInsurerRefreshToken();
  if (!refresh) return false;

  try {
    const res = await fetch(`${API_BASE}/insurer/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      clearInsurerTokens();
      return false;
    }
    const data = await res.json();
    setInsurerTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clearInsurerTokens();
    return false;
  }
}

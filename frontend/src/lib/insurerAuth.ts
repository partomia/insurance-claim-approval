// Same-origin safe base: empty VITE_API_URL → relative paths against own origin.
const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "insurer_token";
const REFRESH_KEY = "insurer_refresh_token";

export function getInsurerToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getInsurerRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setInsurerTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
}

export function clearInsurerTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isInsurerAuthenticated(): boolean {
  return Boolean(getInsurerToken() || getInsurerRefreshToken());
}

export function insurerAuthHeaders(json = false): HeadersInit {
  const token = getInsurerToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
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

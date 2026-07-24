const TOKEN_KEY = "token";
const REFRESH_KEY = "refresh_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
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
    headers.Authorization = `Bearer ${token}`;
  }
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export function logout(): void {
  const refresh = getRefreshToken();
  if (refresh) {
    fetch(`${import.meta.env.VITE_API_URL}/auth/logout`, {
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
    const res = await fetch(`${import.meta.env.VITE_API_URL}/auth/refresh`, {
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

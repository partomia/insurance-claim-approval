import { authHeaders, getRefreshToken, redirectToLogin, refreshSession } from "./auth";

// Backend base URL. When VITE_API_URL is empty/unset the app calls its OWN
// origin with relative paths (single same-origin deploy, e.g. one CML
// Application serving both the built UI and the API). Set VITE_API_URL only
// when the backend lives on a different origin.
const API_URL = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
    this.detail = detail;
  }
}

export function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  // Empty API_URL → relative path against the app's own origin.
  return `${API_URL}${suffix}`;
}

export async function apiFetch(
  path: string,
  options: RequestInit = {},
  { json = false, redirectOn401 = true }: { json?: boolean; redirectOn401?: boolean } = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  const auth = authHeaders(json);
  Object.entries(auth).forEach(([key, value]) => {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  });

  let response = await fetch(apiUrl(path), { ...options, headers });

  if (response.status === 401 && getRefreshToken() && !path.includes("/auth/refresh")) {
    const refreshed = await refreshSession();
    if (refreshed) {
      const retryHeaders = new Headers(options.headers);
      const retryAuth = authHeaders(json);
      Object.entries(retryAuth).forEach(([key, value]) => {
        if (!retryHeaders.has(key)) {
          retryHeaders.set(key, value);
        }
      });
      response = await fetch(apiUrl(path), { ...options, headers: retryHeaders });
    }
  }

  if (response.status === 401 && redirectOn401) {
    redirectToLogin();
  }

  return response;
}

export async function apiJson<T>(
  path: string,
  options: RequestInit = {},
  config?: { json?: boolean; redirectOn401?: boolean }
): Promise<T> {
  const response = await apiFetch(path, options, config);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, error.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

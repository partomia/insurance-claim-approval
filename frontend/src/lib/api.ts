import { authHeaders, getRefreshToken, redirectToLogin, refreshSession } from "./auth";

const API_URL = import.meta.env.VITE_API_URL as string | undefined;

if (!API_URL && import.meta.env.PROD) {
  console.error(
    "VITE_API_URL is not set. Add it in Vercel → Project Settings → Environment Variables, then redeploy."
  );
}

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
  if (!API_URL) {
    throw new Error("VITE_API_URL is not configured");
  }
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;
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

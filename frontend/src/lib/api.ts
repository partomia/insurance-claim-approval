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
  // All API paths already carry the shared "/api" prefix. If VITE_API_URL was
  // (mis)built ending in "/api", naive concatenation doubles it into
  // "/api/api/..." (→ 500s). Drop the base's trailing "/api" in that case so a
  // bad build env can't break every request. Empty API_URL → relative path.
  const base = API_URL.endsWith("/api") && suffix.startsWith("/api/")
    ? API_URL.slice(0, -4)
    : API_URL;
  return `${base}${suffix}`;
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
  return parseJsonResponse<T>(response, path);
}

/**
 * Safely parse a JSON API response. Guards against the case where the backend
 * (or a proxy) returns HTML — e.g. the SPA index.html or a gateway error page —
 * with a 200 or error status. Without this guard, `response.json()` throws a raw
 * "Unexpected token '<'" SyntaxError that crashes the caller.
 */
export async function parseJsonResponse<T>(response: Response, path = ""): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");

  if (!response.ok) {
    if (isJson) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, error?.detail ?? response.statusText);
    }
    // Non-JSON error body (HTML/text) — surface a clean message, not the markup.
    await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText || "Request failed");
  }

  if (!isJson) {
    // 2xx but not JSON: almost always the SPA shell served for an API path,
    // which means the API route wasn't hit (stale deploy / wrong base URL).
    throw new ApiError(
      response.status,
      `Expected JSON from ${path || "the API"} but received ${contentType || "a non-JSON response"}. ` +
        "The API request did not reach the backend."
    );
  }

  return response.json() as Promise<T>;
}

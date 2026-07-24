import { apiUrl, ApiError } from "./api";
import {
  getInsurerRefreshToken,
  insurerAuthHeaders,
  redirectToInsurerLogin,
  refreshInsurerSession,
} from "./insurerAuth";

export async function insurerApiFetch(
  path: string,
  options: RequestInit = {},
  { json = false, redirectOn401 = true }: { json?: boolean; redirectOn401?: boolean } = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  const auth = insurerAuthHeaders(json);
  Object.entries(auth).forEach(([key, value]) => {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  });

  let response = await fetch(apiUrl(path), { ...options, headers });

  if (response.status === 401 && getInsurerRefreshToken() && !path.includes("/insurer/auth/refresh")) {
    const refreshed = await refreshInsurerSession();
    if (refreshed) {
      const retryHeaders = new Headers(options.headers);
      const retryAuth = insurerAuthHeaders(json);
      Object.entries(retryAuth).forEach(([key, value]) => {
        if (!retryHeaders.has(key)) {
          retryHeaders.set(key, value);
        }
      });
      response = await fetch(apiUrl(path), { ...options, headers: retryHeaders });
    }
  }

  if (response.status === 401 && redirectOn401) {
    redirectToInsurerLogin();
  }

  return response;
}

export async function insurerApiJson<T>(
  path: string,
  options: RequestInit = {},
  config?: { json?: boolean; redirectOn401?: boolean }
): Promise<T> {
  const response = await insurerApiFetch(path, options, config);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, error.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

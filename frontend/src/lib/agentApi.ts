import { apiUrl, parseJsonResponse } from "./api";
import {
  agentAuthHeaders,
  getAgentRefreshToken,
  redirectToAgentLogin,
  refreshAgentSession,
} from "./agentAuth";

export async function agentApiFetch(
  path: string,
  options: RequestInit = {},
  { json = false, redirectOn401 = true }: { json?: boolean; redirectOn401?: boolean } = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  const auth = agentAuthHeaders(json);
  Object.entries(auth).forEach(([key, value]) => {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  });

  let response = await fetch(apiUrl(path), { ...options, headers });

  if (response.status === 401 && getAgentRefreshToken() && !path.includes("/agent/auth/refresh")) {
    const refreshed = await refreshAgentSession();
    if (refreshed) {
      const retryHeaders = new Headers(options.headers);
      const retryAuth = agentAuthHeaders(json);
      Object.entries(retryAuth).forEach(([key, value]) => {
        if (!retryHeaders.has(key)) {
          retryHeaders.set(key, value);
        }
      });
      response = await fetch(apiUrl(path), { ...options, headers: retryHeaders });
    }
  }

  if (response.status === 401 && redirectOn401) {
    redirectToAgentLogin();
  }

  return response;
}

export async function agentApiJson<T>(
  path: string,
  options: RequestInit = {},
  config?: { json?: boolean; redirectOn401?: boolean }
): Promise<T> {
  const response = await agentApiFetch(path, options, config);
  return parseJsonResponse<T>(response, path);
}

import axios from "axios";
import { jwtDecode } from "jwt-decode";
import { ACCESS_TOKEN, REFRESH_TOKEN } from "./constants";

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "" });
const credentialPaths = new Set(["/api/token/", "/api/token/refresh/", "/api/token/logout/", "/api/user/register/"]);
let pendingRefresh;

function authenticationTarget(config) {
  const apiOrigin = new URL(api.defaults.baseURL || window.location.origin, window.location.origin).origin;
  const requestURL = new URL(config.url, new URL(config.baseURL || "/", window.location.origin));
  return requestURL.origin === apiOrigin && !credentialPaths.has(requestURL.pathname);
}

function sameAccount(first, second) {
  if (!first || !second) return false;
  try {
    const account = jwtDecode(first).user_id;
    return account != null && account === jwtDecode(second).user_id;
  } catch {
    return false;
  }
}

export async function refreshSession(access) {
  if (!access) return null;
  const currentAccess = localStorage.getItem(ACCESS_TOKEN);
  if (access !== currentAccess) return sameAccount(access, currentAccess) ? currentAccess : null;
  const initialRefresh = localStorage.getItem(REFRESH_TOKEN);
  if (!initialRefresh) return null;
  if (pendingRefresh?.token === initialRefresh) return pendingRefresh.promise;

  async function exchange() {
    const current = localStorage.getItem(ACCESS_TOKEN);
    if (current !== access) return sameAccount(access, current) ? current : null;
    if (localStorage.getItem(REFRESH_TOKEN) !== initialRefresh) return null;
    try {
      const { data } = await api.post("/api/token/refresh/", { refresh: initialRefresh }, { timeout: 10_000 });
      if (localStorage.getItem(ACCESS_TOKEN) !== access || localStorage.getItem(REFRESH_TOKEN) !== initialRefresh) return null;
      localStorage.setItem(ACCESS_TOKEN, data.access);
      if (data.refresh) localStorage.setItem(REFRESH_TOKEN, data.refresh);
      return data.access;
    } catch {
      return null;
    }
  }

  const promise = navigator.locks ? navigator.locks.request("findash-token-refresh", exchange) : exchange();
  pendingRefresh = { token: initialRefresh, promise };
  try {
    return await promise;
  } finally {
    if (pendingRefresh?.promise === promise) pendingRefresh = undefined;
  }
}

export function clearSession() {
  const refresh = localStorage.getItem(REFRESH_TOKEN);
  localStorage.removeItem(ACCESS_TOKEN);
  localStorage.removeItem(REFRESH_TOKEN);
  if (refresh) api.post("/api/token/logout/", { refresh }, { timeout: 8_000 }).catch(() => {});
}

api.interceptors.request.use((config) => {
  if (!authenticationTarget(config)) {
    config.headers.delete("Authorization");
    return config;
  }
  const token = localStorage.getItem(ACCESS_TOKEN);
  if (token && !config.headers.has("Authorization")) config.headers.set("Authorization", `Bearer ${token}`);
  return config;
});

api.interceptors.response.use(undefined, async (error) => {
  const config = error.config;
  if (error.response?.status !== 401 || error.response.data?.code !== "token_not_valid" ||
      !config || config.signal?.aborted || config.authRetried || !authenticationTarget(config)) throw error;
  const access = config.headers.get("Authorization")?.replace(/^Bearer /, "");
  const renewed = await refreshSession(access);
  if (!renewed || config.signal?.aborted || localStorage.getItem(ACCESS_TOKEN) !== renewed) throw error;
  config.authRetried = true;
  config.headers.set("Authorization", `Bearer ${renewed}`);
  return api.request(config);
});

export default api;

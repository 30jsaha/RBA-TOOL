import axios from "axios";
import API_BASE_URL from "../config/api.config";

let accessToken = null;
let currentUserRequest = null;
let currentUserHydrated = false;
let currentUserCache = null;
let refreshRequest = null;

const authClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

const readCookie = (name) => {
  if (typeof document === "undefined") return null;

  const prefix = `${name}=`;
  const parts = document.cookie ? document.cookie.split(";") : [];
  for (const rawPart of parts) {
    const part = rawPart.trim();
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length));
    }
  }
  return null;
};

const normalizeRoles = (roles) => {
  if (!Array.isArray(roles)) return [];
  return roles
    .map((role) => {
      if (typeof role === "string") return role;
      if (role && typeof role.name === "string") return role.name;
      return null;
    })
    .filter(Boolean);
};

const normalizeSessionUser = (payload) => {
  if (!payload) return null;

  const user = payload.user || payload;
  const roles = normalizeRoles(payload.roles || user.roles);
  const permissions = Array.isArray(payload.permissions)
    ? [...new Set(payload.permissions.filter(Boolean))]
    : Array.isArray(user.permissions)
    ? [...new Set(user.permissions.filter(Boolean))]
    : [];

  return {
    id: user.id ?? payload.id ?? null,
    email: user.email ?? payload.email ?? null,
    full_name: user.full_name ?? payload.full_name ?? null,
    roles,
    permissions,
  };
};

export function setAccessToken(token) {
  accessToken = typeof token === "string" && token.trim() ? token.trim() : null;
  return accessToken;
}

const storeUser = (payload) => {
  currentUserCache = normalizeSessionUser(payload);
  return currentUserCache;
};

export function getUser() {
  return currentUserCache;
}

export function getToken() {
  return accessToken;
}

export function getPermissions() {
  const user = getUser();
  return Array.isArray(user?.permissions) ? user.permissions : [];
}

export function hasPermission(permission) {
  if (!permission) return true;
  return getPermissions().includes(permission);
}

export function clearSession() {
  accessToken = null;
  currentUserRequest = null;
  currentUserHydrated = false;
  currentUserCache = null;
  refreshRequest = null;
}

const getRefreshCsrfHeader = () => {
  const csrfToken = readCookie("rba_refresh_csrf");
  return csrfToken ? { "X-CSRF-TOKEN": csrfToken } : {};
};

export async function refreshAccessToken() {
  if (refreshRequest) return refreshRequest;

  refreshRequest = authClient
    .post("/auth/refresh", {}, { headers: getRefreshCsrfHeader() })
    .then((res) => {
      const nextAccessToken = res?.data?.access || null;
      setAccessToken(nextAccessToken);
      return nextAccessToken;
    })
    .catch((error) => {
      clearSession();
      throw error;
    })
    .finally(() => {
      refreshRequest = null;
    });

  return refreshRequest;
}

export async function fetchCurrentUser(tokenOverride = null) {
  const token = tokenOverride || getToken() || (await refreshAccessToken().catch(() => null));
  if (!token) return null;

  const res = await authClient.get("/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });

  currentUserHydrated = true;
  return storeUser(res.data || {});
}

export async function ensureCurrentUser() {
  if (currentUserHydrated && currentUserCache && Array.isArray(currentUserCache.permissions)) {
    return currentUserCache;
  }

  if (!currentUserRequest) {
    currentUserRequest = (async () => {
      const token = getToken() || (await refreshAccessToken().catch(() => null));
      if (!token) {
        clearSession();
        return null;
      }

      try {
        return await fetchCurrentUser(token);
      } catch (error) {
        clearSession();
        throw error;
      }
    })().finally(() => {
      currentUserRequest = null;
    });
  }

  try {
    return await currentUserRequest;
  } catch {
    return null;
  }
}

export async function login(email, password) {
  try {
    const res = await authClient.post("/login", { email, password });

    const { access, user } = res.data || {};
    setAccessToken(access);
    if (user) storeUser(user);

    if (access) {
      try {
        const currentUser = await fetchCurrentUser(access);
        return { ...(res.data || {}), user: currentUser };
      } catch {
        // Keep login working even if /me temporarily fails.
      }
    }

    return { ...(res.data || {}), user: getUser() };
  } catch (err) {
    if (err.response) {
      throw err.response;
    }
    throw err;
  }
}

export async function logout() {
  try {
    await authClient.post("/auth/logout", {}, { headers: getRefreshCsrfHeader() });
  } catch {
    // Clear client state even if the server-side cookie is already gone.
  } finally {
    clearSession();
  }
}

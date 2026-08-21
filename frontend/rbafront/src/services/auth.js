import axios from "axios";
import API_BASE_URL from "../config/api.config";

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const USER_KEY = "user";

let currentUserRequest = null;
let currentUserHydrated = false;
let currentUserCache = null;

const safeParseJson = (value) => {
  try {
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
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

const storeUser = (payload) => {
  const normalizedUser = normalizeSessionUser(payload);
  currentUserCache = normalizedUser;
  if (normalizedUser) {
    localStorage.setItem(USER_KEY, JSON.stringify(normalizedUser));
  }
  return normalizedUser;
};

export function getUser() {
  if (currentUserCache) return currentUserCache;
  currentUserCache = safeParseJson(localStorage.getItem(USER_KEY));
  return currentUserCache;
}

export function getToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getPermissions() {
  const user = getUser();
  return Array.isArray(user?.permissions) ? user.permissions : [];
}

export function hasPermission(permission) {
  if (!permission) return true;
  return getPermissions().includes(permission);
}

export function logout() {
  currentUserRequest = null;
  currentUserHydrated = false;
  currentUserCache = null;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function fetchCurrentUser() {
  const token = getToken();
  if (!token) return null;

  const res = await axios.get(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  currentUserHydrated = true;
  return storeUser(res.data || {});
}

export async function ensureCurrentUser() {
  const token = getToken();
  if (!token) return null;

  const existingUser = getUser();
  if (currentUserHydrated && existingUser && Array.isArray(existingUser.permissions)) {
    return existingUser;
  }

  if (!currentUserRequest) {
    currentUserRequest = fetchCurrentUser().finally(() => {
      currentUserRequest = null;
    });
  }

  return currentUserRequest;
}

export async function login(email, password) {
  try {
    const res = await axios.post(`${API_BASE_URL}/login`, { email, password });

    const { access, refresh, user } = res.data || {};

    if (access) localStorage.setItem(ACCESS_TOKEN_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
    if (user) storeUser(user);

    if (access) {
      try {
        const currentUser = await fetchCurrentUser();
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

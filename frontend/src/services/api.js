import axios from "axios";
import API_BASE_URL from "../config/api.config";
import { clearSession, getToken, refreshAccessToken } from "./auth";

export const getAccessToken = () => getToken();

const toastSessionExpired = async () => {
  try {
    const { default: Swal } = await import("sweetalert2");
    await Swal.fire({
      toast: true,
      position: "top-end",
      icon: "warning",
      title: "Session expired. Please login again.",
      showConfirmButton: false,
      timer: 3500,
      timerProgressBar: true,
    });
  } catch {
    // no-op: avoid crashing on toast failure
  }
};

const redirectToLogin = () => {
  const path = window.location?.pathname || "";
  if (path === "/" || path.startsWith("/login")) return;
  window.location.assign("/");
};

const isAuthEndpointRequest = (url) => {
  const requestUrl = String(url || "");
  return (
    requestUrl.includes("/auth/login") ||
    requestUrl.includes("/login") ||
    requestUrl.includes("/auth/refresh") ||
    requestUrl.includes("/auth/logout")
  );
};

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

api.interceptors.request.use(async (config) => {
  config.headers = config.headers || {};

  if (config.headers.Authorization) {
    return config;
  }

  let token = getToken();
  if (!token && !isAuthEndpointRequest(config.url)) {
    try {
      token = await refreshAccessToken();
    } catch {
      token = null;
    }
  }

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status;
    const message = error?.response?.data?.message;
    const originalRequest = error?.config || {};

    const isAuthFailure =
      status === 401 ||
      (typeof message === "string" &&
        (message.toLowerCase().includes("missing or invalid token") ||
          message.toLowerCase().includes("token expired")));

    const isAuthEndpoint = isAuthEndpointRequest(originalRequest?.url);

    if (isAuthFailure && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      try {
        const newAccessToken = await refreshAccessToken();
        if (newAccessToken) {
          originalRequest.headers = originalRequest.headers || {};
          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
          return api(originalRequest);
        }
      } catch {
        // Fall through to session cleanup below.
      }
    }

    if (isAuthFailure) {
      clearSession();
      await toastSessionExpired();
      redirectToLogin();
    }

    return Promise.reject(error);
  }
);

export default api;

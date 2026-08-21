import axios from "axios";
import API_BASE_URL from "../config/api.config";

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const USER_KEY = "user";

export const getAccessToken = () => localStorage.getItem(ACCESS_TOKEN_KEY);

export const clearSession = () => {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
};

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

const api = axios.create({
  baseURL: API_BASE_URL,
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status;
    const message = error?.response?.data?.message;

    const isAuthFailure =
      status === 401 ||
      (typeof message === "string" &&
        (message.toLowerCase().includes("missing or invalid token") ||
          message.toLowerCase().includes("token expired")));

    if (isAuthFailure) {
      clearSession();
      await toastSessionExpired();
      redirectToLogin();
    }

    return Promise.reject(error);
  }
);

export default api;

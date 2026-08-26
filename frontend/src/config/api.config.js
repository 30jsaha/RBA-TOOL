const isLoopbackHost = (value) => value === "localhost" || value === "127.0.0.1";

const normalizeLoopbackOrigin = (raw) => {
  if (typeof window === "undefined") return raw;

  try {
    const url = new URL(raw);
    const currentHost = window.location.hostname;

    if (isLoopbackHost(url.hostname) && isLoopbackHost(currentHost) && url.hostname !== currentHost) {
      url.hostname = currentHost;
      return url.toString();
    }
  } catch {
    return raw;
  }

  return raw;
};

const normalizeApiBaseUrl = (raw) => {
  const fallback = "http://localhost:5000/api";
  const candidate = normalizeLoopbackOrigin((raw || fallback).toString().trim());
  const trimmed = candidate.replace(/\/+$/, "");

  if (typeof window !== "undefined") {
    try {
      const currentHost = window.location.hostname;
      const currentPort = window.location.port;
      const url = new URL(trimmed);
      const isViteDevServer = ["4173", "5173", "5174", "5175"].includes(currentPort);

      if (isViteDevServer && isLoopbackHost(currentHost) && isLoopbackHost(url.hostname)) {
        return "/api";
      }
    } catch {
      // Fall back to absolute API base below.
    }
  }

  if (!trimmed) return fallback;
  if (trimmed.endsWith("/api")) return trimmed;
  return `${trimmed}/api`;
};

export const API_BASE_URL = normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
export const SERVER_BASE_URL = API_BASE_URL === "/api" ? "" : API_BASE_URL.replace(/\/api$/, "");

export default API_BASE_URL;

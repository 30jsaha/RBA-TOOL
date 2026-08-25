const normalizeApiBaseUrl = (raw) => {
  const fallback = "http://localhost:5000/api";
  const candidate = (raw || fallback).toString().trim();
  const trimmed = candidate.replace(/\/+$/, "");

  if (!trimmed) return fallback;
  if (trimmed.endsWith("/api")) return trimmed;
  return `${trimmed}/api`;
};

export const API_BASE_URL = normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
export const SERVER_BASE_URL = API_BASE_URL.replace(/\/api$/, "");

export default API_BASE_URL;


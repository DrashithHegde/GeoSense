const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

export function getApiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

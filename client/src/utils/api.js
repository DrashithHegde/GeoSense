// ─────────────────────────────────────────────────────────────────────────────
// Backend access: which server, which city.
//
// VITE_API_URLS lists one or more backends in order of preference, e.g.
//   VITE_API_URLS=https://geosense-api.azurewebsites.net,https://geosense-api.onrender.com
// (VITE_API_URL with a single URL also works). Requests go to the first backend that answers;
// when it stops answering (network error, or a hosting platform's error page such as an Azure
// app stopped after its credits ran out) the next one is used and remembered for the session.
//
// Every /api/ request carries ?city=<id> for the city on screen (set with setApiCity).
// ─────────────────────────────────────────────────────────────────────────────

const RAW = import.meta.env.VITE_API_URLS || import.meta.env.VITE_API_URL || "http://localhost:8000";
const BASES = RAW.split(",")
  .map((s) => s.trim().replace(/\/$/, ""))
  .filter(Boolean);
const STORE_KEY = "geosense.apiBase";
const FAILOVER_STATUS = new Set([403, 404, 502, 503, 504]);

let active = 0;
try {
  const saved = sessionStorage.getItem(STORE_KEY);
  const i = BASES.indexOf(saved);
  if (i >= 0) active = i;
} catch {
  /* storage unavailable: start with the first backend */
}

let city = null;

export function setApiCity(id) {
  city = id || null;
}

export function getApiCity() {
  return city;
}

export function getApiBase() {
  return BASES[active];
}

function setActive(i) {
  active = i;
  try {
    sessionStorage.setItem(STORE_KEY, BASES[i]);
  } catch {
    /* ignore */
  }
}

function build(base, path) {
  if (/^https?:\/\//i.test(path)) return path;
  const p = path.startsWith("/") ? path : `/${path}`;
  let url = `${base}${p}`;
  if (city && p.startsWith("/api/") && !/[?&]city=/.test(p)) {
    url += `${p.includes("?") ? "&" : "?"}city=${encodeURIComponent(city)}`;
  }
  return url;
}

// URL on the backend in use (also for map images: /surface-assets/<city>/...)
export function getApiUrl(path) {
  return build(BASES[active], path);
}

// A platform error page (HTML), not an answer from GeoSense's API (which always sends JSON)
function isPlatformError(res) {
  if (!FAILOVER_STATUS.has(res.status)) return false;
  const type = res.headers.get("content-type") || "";
  return !type.includes("application/json");
}

// fetch() against the backend in use, moving to the next backend when this one is down.
export async function apiFetch(path, options = {}) {
  const order = [active, ...BASES.map((_, i) => i).filter((i) => i !== active)];
  let lastError = null;
  for (let n = 0; n < order.length; n += 1) {
    const i = order[n];
    try {
      const res = await fetch(build(BASES[i], path), options);
      if (isPlatformError(res) && n < order.length - 1) {
        lastError = new Error(`backend ${BASES[i]} answered ${res.status}`);
        continue;
      }
      if (i !== active) setActive(i);
      return res;
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      lastError = err;
    }
  }
  throw lastError || new Error("No GeoSense backend reachable");
}

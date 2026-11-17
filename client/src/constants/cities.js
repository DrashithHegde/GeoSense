// ─────────────────────────────────────────────────────────────────────────────
// CITY CONFIGURATION — the cities GeoSense covers (same ids, centres and zoom as the backend's
// server/app/core/cities.py). Every value shown for a city comes from the backend; nothing here
// is data. Whether a city's layers are ready is asked from GET /api/cities.
// ─────────────────────────────────────────────────────────────────────────────

export const CITY_CONFIG = {
  mumbai: {
    id: "mumbai",
    label: "Mumbai",
    region: "Mumbai, Thane and Mira-Bhayandar",
    center: [72.8777, 19.076],
    zoom: 10.8,
  },
  delhi: {
    id: "delhi",
    label: "Delhi",
    region: "Delhi (National Capital Territory)",
    center: [77.1025, 28.6448],
    zoom: 10.2,
  },
  bengaluru: {
    id: "bengaluru",
    label: "Bengaluru",
    region: "Bengaluru (BBMP area)",
    center: [77.5946, 12.9716],
    zoom: 10.8,
  },
};

export const CITY_IDS = Object.keys(CITY_CONFIG);

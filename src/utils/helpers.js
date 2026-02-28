import { SEVERITY_COLORS } from "../constants/layers";

// ─────────────────────────────────────────────────────────────────────────────
// SEVERITY UTILS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Returns the hex color for a given numeric severity score (0–100)
 */
export function getSeverityColor(score) {
  if (score >= 85) return "#ff3b3b";
  if (score >= 70) return "#ff8c00";
  if (score >= 50) return "#ffd32a";
  return "#1dd1a1";
}

/**
 * Returns the severity config object from SEVERITY_COLORS
 */
export function getSeverityConfig(type) {
  return SEVERITY_COLORS[type] || SEVERITY_COLORS.moderate;
}

/**
 * Returns a human-readable severity label
 */
export function getSeverityLabel(score) {
  if (score >= 85) return "CRITICAL";
  if (score >= 70) return "SEVERE";
  if (score >= 50) return "HIGH";
  return "MODERATE";
}

// ─────────────────────────────────────────────────────────────────────────────
// TREND DATA
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Generates mock 14-day trend data ending at `endValue`
 * Replace with real API call in production
 */
export function generateTrend(endValue, points = 14) {
  const pts = [];
  let v = endValue * 0.55;
  for (let i = 0; i < points - 1; i++) {
    v = Math.max(15, Math.min(100, v + (Math.random() - 0.4) * 12));
    pts.push(+v.toFixed(1));
  }
  pts.push(endValue);
  return pts;
}

// ─────────────────────────────────────────────────────────────────────────────
// GEOJSON BUILDER  (used by Mapbox heatmap source)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Converts city zones into a Mapbox-ready GeoJSON FeatureCollection
 */
export function buildGeoJSON(city) {
  if (!city) return { type: "FeatureCollection", features: [] };

  return {
    type: "FeatureCollection",
    features: city.zones.map((zone) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: zone.coords,
      },
      properties: {
        severity: zone.severity / 100,
        color:    getSeverityConfig(zone.type).hex,
        zone:     JSON.stringify(zone),
      },
    })),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// TIME UTILS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Returns a formatted UTC timestamp string: YYYY-MM-DD HH:MM:SSZ
 */
export function formatUTCTime(date = new Date()) {
  const p = (v) => String(v).padStart(2, "0");
  return (
    `${date.getUTCFullYear()}-${p(date.getUTCMonth() + 1)}-${p(date.getUTCDate())} ` +
    `${p(date.getUTCHours())}:${p(date.getUTCMinutes())}:${p(date.getUTCSeconds())}Z`
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CLASS MERGE HELPER (lightweight cx utility)
// ─────────────────────────────────────────────────────────────────────────────

export function cx(...classes) {
  return classes.filter(Boolean).join(" ");
}

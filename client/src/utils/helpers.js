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

/**
 * Returns CPCB AQI band label for an AQI value
 */
export function getAqiCpcbBand(aqi) {
  const value = Math.max(0, Math.min(500, Number(aqi) || 0));
  if (value <= 50) return "GOOD";
  if (value <= 100) return "SATISFACTORY";
  if (value <= 200) return "MODERATE";
  if (value <= 300) return "POOR";
  if (value <= 400) return "VERY POOR";
  return "SEVERE";
}

/**
 * NDVI vegetation condition band
 */
export function getNdviBand(ndvi) {
  const value = Math.max(-1, Math.min(1, Number(ndvi) || 0));
  if (value < 0.0) return "NON-VEGETATED";
  if (value < 0.2) return "VERY LOW VEGETATION";
  if (value < 0.4) return "LOW VEGETATION";
  if (value < 0.6) return "MODERATE VEGETATION";
  return "HIGH VEGETATION";
}

/**
 * NDWI moisture/water condition band
 */
export function getNdwiBand(ndwi) {
  const value = Math.max(-1, Math.min(1, Number(ndwi) || 0));
  if (value < -0.1) return "VERY LOW MOISTURE";
  if (value < 0.05) return "LOW MOISTURE";
  if (value < 0.2) return "MODERATE MOISTURE";
  if (value < 0.35) return "HIGH MOISTURE";
  return "VERY HIGH MOISTURE";
}

/**
 * LST thermal condition band (°C)
 */
export function getLstBand(lst) {
  const value = Number(lst) || 0;
  if (value < 28) return "COOL";
  if (value < 32) return "MILD";
  if (value < 36) return "WARM";
  if (value < 40) return "HOT";
  return "EXTREME HEAT";
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
// METRIC DERIVATION (mock-to-physical mapping)
// ─────────────────────────────────────────────────────────────────────────────

export function getZoneMetrics(zone) {
  if (!zone) {
    return { aqi: 0, ndvi: 0, ndwi: 0, lst: 0 };
  }

  const hasNativeMetrics =
    zone.aqi !== undefined &&
    zone.ndvi !== undefined &&
    zone.ndwi !== undefined &&
    zone.lst !== undefined;

  if (hasNativeMetrics) {
    return {
      aqi: Number(zone.aqi),
      ndvi: Number(zone.ndvi),
      ndwi: Number(zone.ndwi),
      lst: Number(zone.lst),
    };
  }

  // Backward-compatible mapping from legacy mock fields:
  // air(0-100), water(0-100), land(0-100), severity(0-100)
  const air = Number(zone.air ?? 0);
  const water = Number(zone.water ?? 0);
  const land = Number(zone.land ?? 0);
  const severity = Number(zone.severity ?? 0);

  // AQI approx range: 0-500 (higher = worse)
  const aqi = Math.round(35 + air * 3.1);

  // NDVI approx range: -0.20 to 0.80 (higher vegetation = better)
  const ndvi = +(Math.max(-0.2, Math.min(0.8, -0.2 + (land / 100) * 1.0))).toFixed(2);

  // NDWI approx range: -0.30 to 0.60 (higher water presence = better)
  const ndwi = +(Math.max(-0.3, Math.min(0.6, -0.3 + (water / 100) * 0.9))).toFixed(2);

  // LST approx range: 24°C to 47°C (higher = hotter)
  const lst = +(24 + severity * 0.18 + (100 - land) * 0.03).toFixed(1);

  return { aqi, ndvi, ndwi, lst };
}

export function getMetricDisplay(metricId, metrics) {
  if (!metrics) return "—";

  switch (metricId) {
    case "aqi":
      return `${metrics.aqi}`;
    case "ndvi":
      return `${metrics.ndvi.toFixed(2)}`;
    case "ndwi":
      return `${metrics.ndwi.toFixed(2)}`;
    case "lst":
      return `${metrics.lst.toFixed(1)}°C`;
    case "all":
      return "Composite";
    default:
      return "—";
  }
}

function clampScore(value) {
  return Math.max(0, Math.min(100, value));
}

function interpolate(value, fromMin, fromMax, toMin, toMax) {
  if (fromMax === fromMin) return toMax;
  const ratio = (value - fromMin) / (fromMax - fromMin);
  return toMin + (toMax - toMin) * ratio;
}

// CPCB AQI bands mapped to app severity score (0-100)
// CPCB bands:
// 0-50 Good, 51-100 Satisfactory, 101-200 Moderate,
// 201-300 Poor, 301-400 Very Poor, 401-500 Severe
function normalizeAqiCpcb(aqi) {
  const value = Math.max(0, Math.min(500, Number(aqi) || 0));

  if (value <= 50) return interpolate(value, 0, 50, 18, 28);
  if (value <= 100) return interpolate(value, 51, 100, 28, 45);
  if (value <= 200) return interpolate(value, 101, 200, 50, 69);
  if (value <= 300) return interpolate(value, 201, 300, 70, 84);
  if (value <= 400) return interpolate(value, 301, 400, 85, 94);
  return interpolate(value, 401, 500, 95, 100);
}

// Lower NDVI means higher vegetation stress (worse)
function normalizeNdviStress(ndvi) {
  const value = Math.max(-0.2, Math.min(0.8, Number(ndvi) || 0));

  if (value <= 0.0) return interpolate(value, -0.2, 0.0, 100, 90);
  if (value <= 0.1) return interpolate(value, 0.0, 0.1, 90, 80);
  if (value <= 0.2) return interpolate(value, 0.1, 0.2, 80, 70);
  if (value <= 0.35) return interpolate(value, 0.2, 0.35, 70, 55);
  if (value <= 0.5) return interpolate(value, 0.35, 0.5, 55, 40);
  return interpolate(value, 0.5, 0.8, 40, 20);
}

// App semantics: higher NDWI indicates higher water anomaly stress
function normalizeNdwiStress(ndwi) {
  const value = Math.max(-0.3, Math.min(0.6, Number(ndwi) || 0));

  if (value <= 0.0) return interpolate(value, -0.3, 0.0, 20, 40);
  if (value <= 0.2) return interpolate(value, 0.0, 0.2, 40, 60);
  if (value <= 0.35) return interpolate(value, 0.2, 0.35, 60, 75);
  if (value <= 0.5) return interpolate(value, 0.35, 0.5, 75, 90);
  return interpolate(value, 0.5, 0.6, 90, 100);
}

// Higher LST means higher thermal stress
function normalizeLstStress(lst) {
  const value = Math.max(20, Math.min(50, Number(lst) || 0));

  if (value <= 30) return interpolate(value, 20, 30, 20, 35);
  if (value <= 34) return interpolate(value, 30, 34, 35, 55);
  if (value <= 38) return interpolate(value, 34, 38, 55, 70);
  if (value <= 42) return interpolate(value, 38, 42, 70, 85);
  return interpolate(value, 42, 50, 85, 100);
}

export function normalizeMetric(metricId, metrics) {
  if (!metrics) return 0;

  switch (metricId) {
    case "aqi":
      return clampScore(normalizeAqiCpcb(metrics.aqi));
    case "ndvi":
      return clampScore(normalizeNdviStress(metrics.ndvi));
    case "ndwi":
      return clampScore(normalizeNdwiStress(metrics.ndwi));
    case "lst":
      return clampScore(normalizeLstStress(metrics.lst));
    default:
      return 0;
  }
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
        color: getSeverityConfig(zone.type).hex,
        zone: JSON.stringify(zone),
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

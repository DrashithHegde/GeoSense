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
 * Water Health condition band. Higher backend score means better condition.
 */
export function getWaterHealthBand(score) {
  if (score === null || score === undefined) return "UNAVAILABLE";
  const value = Math.max(0, Math.min(1, Number(score)));
  if (value >= 0.75) return "GOOD CONDITION";
  if (value >= 0.5) return "WATCH";
  return "POTENTIAL CONCERN";
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
    return { aqi: null, ndvi: null, lst: null, water_health_score: null };
  }

  const hasNativeMetrics =
    zone.aqi !== undefined &&
    zone.ndvi !== undefined &&
    zone.lst !== undefined;

  if (hasNativeMetrics) {
    return {
      aqi: zone.aqi == null ? null : Number(zone.aqi),
      ndvi: zone.ndvi == null ? null : Number(zone.ndvi),
      lst: zone.lst == null ? null : Number(zone.lst),
      water_health_score: zone.water_health_score == null ? null : Number(zone.water_health_score),
    };
  }

  return {
    aqi: zone.aqi ?? null,
    ndvi: zone.ndvi ?? null,
    lst: zone.lst ?? null,
    water_health_score: zone.water_health_score ?? null,
  };
}

export function getMetricDisplay(metricId, metrics) {
  if (!metrics) return "—";

  switch (metricId) {
    case "aqi":
      return metrics.aqi == null ? "N/A" : `${metrics.aqi}`;
    case "ndvi":
      return metrics.ndvi == null ? "N/A" : `${metrics.ndvi.toFixed(2)}`;
    case "water_health":
      return metrics.water_health_score == null ? "N/A" : `${(metrics.water_health_score * 100).toFixed(0)}%`;
    case "lst":
      return metrics.lst == null ? "N/A" : `${metrics.lst.toFixed(1)}°C`;
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

function normalizeWaterHealthStress(score) {
  if (score === null || score === undefined) return null;
  return clampScore((1 - Number(score)) * 100);
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
    case "water_health":
      return normalizeWaterHealthStress(metrics.water_health_score);
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
 * Converts zones into a Mapbox-ready GeoJSON FeatureCollection.
 * @param {object} city - city config object (used for non-Mumbai placeholder cities)
 * @param {Array}  liveZones - real zones from backend (optional; takes precedence when provided)
 */
export function buildGeoJSON(city, liveZones) {
  // Prefer real backend zones when provided
  const zones = (liveZones && liveZones.length > 0)
    ? liveZones
    : (city?.zones ?? []);

  if (!zones.length) return { type: "FeatureCollection", features: [] };

  return {
    type: "FeatureCollection",
    features: zones.map((zone) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: zone.coords,
      },
      properties: {
        severity: zone.severity == null ? 0 : zone.severity / 100,
        composite_score: zone.composite?.score == null ? null : zone.composite.score / 100,
        water_health_score: zone.water_health_score == null ? null : zone.water_health_score,
        water_health_stress: zone.water_health_score == null ? null : 1 - zone.water_health_score,
        water_health_available: zone.water_health_score != null,
        aqi_stress: zone.composite?.normalized_components?.aqi == null ? null : zone.composite.normalized_components.aqi / 100,
        aqi_weight: zone.aqi == null ? null : Math.max(0, Math.min(1, Number(zone.aqi) / 500)),
        ndvi_stress: zone.composite?.normalized_components?.ndvi == null ? null : zone.composite.normalized_components.ndvi / 100,
        lst_stress: zone.composite?.normalized_components?.lst == null ? null : zone.composite.normalized_components.lst / 100,
        color: getSeverityConfig(zone.type).hex,
        zone: JSON.stringify(zone),
      },
    })),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// POLYGON GEOJSON BUILDER  (primary map visualization)
// Builds Mapbox-ready polygon FeatureCollection from backend zone data.
// Each feature carries normalized metric values for fill-color expressions.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Clamps a value between 0 and 1 (returns null if value is null/undefined)
 */
function clamp01(v) {
  if (v == null) return null;
  return Math.max(0, Math.min(1, v));
}

/**
 * Normalizes AQI (0–500 CPCB scale) to 0–1 stress value.
 * Higher AQI → higher norm (worse).
 */
function normalizeAqi(aqi) {
  if (aqi == null) return null;
  return clamp01(Number(aqi) / 500);
}

/**
 * Normalizes NDVI (-1 to 1) to 0–1 STRESS value.
 * Lower NDVI → higher stress (inverted).
 */
function normalizeNdviToStress(ndvi) {
  if (ndvi == null) return null;
  // Map NDVI range [-0.2, 0.8] → stress [1.0, 0.0]
  const v = Math.max(-0.2, Math.min(0.8, Number(ndvi)));
  return clamp01((0.8 - v) / 1.0);
}

/**
 * Normalizes LST (°C) to 0–1 stress value.
 * Higher LST → higher stress.
 */
function normalizeLst(lst) {
  if (lst == null) return null;
  // Map [20°C, 50°C] → [0, 1]
  const v = Math.max(20, Math.min(50, Number(lst)));
  return clamp01((v - 20) / 30);
}

/**
 * Normalizes Water Health score (0–1 condition) to 0–1 STRESS value.
 * Higher score = better water → lower stress (inverted).
 */
function normalizeWaterHealthToStress(score) {
  if (score == null) return null;
  return clamp01(1 - Number(score));
}

/**
 * Converts backend zones into a Mapbox-ready FeatureCollection of polygons.
 * Uses the actual zone MultiPolygon geometries from the backend.
 * Each feature carries normalized 0–1 metric stress values for paint expressions.
 *
 * @param {Array} zones - real zones from backend (with .geometry from ST_AsGeoJSON)
 * @returns {GeoJSON.FeatureCollection}
 */
export function buildZonesGeoJSON(zones) {
  if (!zones || zones.length === 0) {
    return { type: "FeatureCollection", features: [] };
  }

  const features = [];

  for (const zone of zones) {
    // Use actual polygon geometry if available, fallback to Point centroid
    const geometry = zone.geometry
      ? zone.geometry
      : zone.coords
        ? { type: "Point", coordinates: zone.coords }
        : null;

    if (!geometry) continue;

    // Composite normalized value from backend (already 0-100 → convert to 0-1)
    const compositeNorm = zone.composite?.score != null
      ? clamp01(zone.composite.score / 100)
      : null;

    features.push({
      type: "Feature",
      id: zone.id,   // promoteId: "id" needs this at Feature level
      geometry: geometry,
      properties: {
        // Identifiers
        id: zone.id,
        name: zone.name,
        ward: zone.ward,

        // Normalized 0–1 values for Mapbox paint expressions
        aqi_norm: normalizeAqi(zone.aqi),
        ndvi_norm: normalizeNdviToStress(zone.ndvi),
        lst_norm: normalizeLst(zone.lst),
        water_norm: normalizeWaterHealthToStress(zone.water_health_score),
        composite_norm: compositeNorm,

        // Raw values for click retrieval
        aqi: zone.aqi,
        ndvi: zone.ndvi,
        lst: zone.lst,
        water_health_score: zone.water_health_score,

        // Serialized full zone for click handler
        zone_json: JSON.stringify(zone),
      },
    });
  }

  return { type: "FeatureCollection", features };
}

export function buildMunicipalitiesGeoJSON(municipalities) {
  if (!municipalities || municipalities.length === 0) {
    return { type: "FeatureCollection", features: [] };
  }

  const features = [];
  for (const muni of municipalities) {
    if (!muni.geometry) continue;

    const compositeNorm = muni.composite_score != null
      ? clamp01(muni.composite_score / 100)
      : null;

    features.push({
      type: "Feature",
      id: muni.id,
      geometry: muni.geometry,
      properties: {
        id: muni.id,
        name: muni.name,
        aqi_norm: normalizeAqi(muni.aqi),
        ndvi_norm: normalizeNdviToStress(muni.ndvi),
        lst_norm: normalizeLst(muni.lst),
        water_norm: null, // Water health is handled separately
        composite_norm: compositeNorm,
        aqi: muni.aqi,
        ndvi: muni.ndvi,
        lst: muni.lst,
        composite_score: muni.composite_score,
        zone_count: muni.zone_count,
        representative_zone_id: muni.representative_zone_id,
        // Mock a zone object for the InsightPanel using representative ID + aggregated metrics
        zone_json: JSON.stringify({
          id: muni.representative_zone_id,
          name: muni.name,
          aqi: muni.aqi,
          ndvi: muni.ndvi,
          lst: muni.lst,
          water_health_score: muni.water_health_score,
          composite: { score: muni.composite_score },
          // Derive a representative coordinate from the polygon geometry centroid bbox.
          // InsightPanel and DeepAnalysisOverlay both display zone.coords[0]/[1].
          coords: (() => {
            try {
              const geom = typeof muni.geometry === "string" ? JSON.parse(muni.geometry) : muni.geometry;
              const ring = geom?.coordinates?.[0]?.[0] ?? geom?.coordinates?.[0];
              if (!ring || ring.length === 0) return null;
              // Compute bbox centre of the outer ring
              const points = Array.isArray(ring[0]) ? ring : [ring];
              let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
              for (const pt of points) {
                if (pt[0] < minLng) minLng = pt[0];
                if (pt[0] > maxLng) maxLng = pt[0];
                if (pt[1] < minLat) minLat = pt[1];
                if (pt[1] > maxLat) maxLat = pt[1];
              }
              return [(minLng + maxLng) / 2, (minLat + maxLat) / 2];
            } catch (_) { return null; }
          })(),
        }),
      }
    });
  }
  return { type: "FeatureCollection", features };
}

export function buildWaterBodiesGeoJSON(waterBodies) {
  if (!waterBodies || waterBodies.length === 0) {
    return { type: "FeatureCollection", features: [] };
  }

  const features = [];
  for (const wb of waterBodies) {
    if (!wb.geometry) continue;

    features.push({
      type: "Feature",
      id: wb.id,
      geometry: wb.geometry,
      properties: {
        id: wb.id,
        name: wb.name,
        water_norm: normalizeWaterHealthToStress(wb.water_health_score),
        water_health_score: wb.water_health_score,
        water_health_status: wb.water_health_status,
      }
    });
  }
  return { type: "FeatureCollection", features };
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

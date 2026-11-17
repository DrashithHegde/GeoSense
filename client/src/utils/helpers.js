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
 * Water Health is a 0–1 satellite proxy whose real values sit in a narrow range
 * (about 0.39–0.49 in Mumbai), so fixed 0–100% bands would call almost every
 * water body a concern. Bands are therefore relative to all detected water cells.
 */
export function waterBandFromPercentile(p) {
  if (p === null || p === undefined || !Number.isFinite(Number(p))) return null;
  const v = Number(p);
  if (v < 10) return "POTENTIAL CONCERN";
  if (v < 30) return "WATCH";
  if (v < 70) return "TYPICAL";
  return "BETTER THAN MOST";
}

export function waterPercentileFromExplanation(explanationData) {
  const ev = explanationData?.evidence;
  const p = ev?.models?.water_health?.percentile ?? ev?.cell?.city_percentiles?.wh_mean;
  return p === null || p === undefined ? null : Number(p);
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

// The city's municipality polygons (the map's base layer and click target), with their
// snapshot means normalised to 0..1 stress for the base colour when no heatmap is shown.
export function buildMunicipalitiesGeoJSON(municipalities) {
  const features = (municipalities || [])
    .filter((muni) => muni.geometry)
    .map((muni) => ({
      type: "Feature",
      id: muni.id,
      geometry: muni.geometry,
      properties: {
        id: muni.id,
        name: muni.name,
        aqi_norm: normalizeAqi(muni.aqi),
        ndvi_norm: normalizeNdviToStress(muni.ndvi),
        lst_norm: normalizeLst(muni.lst),
        water_norm: normalizeWaterHealthToStress(muni.water_health_score),
        composite_norm: muni.composite_score != null ? clamp01(muni.composite_score / 100) : null,
        aqi: muni.aqi,
        ndvi: muni.ndvi,
        lst: muni.lst,
        composite_score: muni.composite_score,
        cell_count: muni.cell_count,
      },
    }));
  return { type: "FeatureCollection", features };
}

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

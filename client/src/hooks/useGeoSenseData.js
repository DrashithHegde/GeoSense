import { useState, useEffect, useCallback, useRef } from "react";
import { getApiUrl } from "../utils/api";

// ─────────────────────────────────────────────────────────────────────────────
// useGeoSenseData
// Fetches /api/metrics/latest and /api/anomalies, joins by zone_id.
// Returns real 189-zone data for Mumbai.
// For Bengaluru / New Delhi, returns empty zones (no fabricated data).
// ─────────────────────────────────────────────────────────────────────────────
export function useGeoSenseData(activeCity) {
  const [zones, setZones] = useState([]);
  const [liveMunicipalities, setLiveMunicipalities] = useState([]);
  const [waterBodies, setWaterBodies] = useState([]);
  const [aqiSurface, setAqiSurface] = useState(null);
  const [aqiSurfaceStatus, setAqiSurfaceStatus] = useState("idle");
  const [aqiSurfaceInfo, setAqiSurfaceInfo] = useState(null);
  const [mlSummary, setMlSummary] = useState(null);
  const [ndviSurface, setNdviSurface] = useState(null);
  const [lstSurface, setLstSurface] = useState(null);
  const [waterHealthSurface, setWaterHealthSurface] = useState(null);
  const [compositeSurface, setCompositeSurface] = useState(null);
  const [boundary, setBoundary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    // ═══════════════════════════════════════════════════════════════════════════
    // NDVI FETCH TRIGGER DIAGNOSTIC
    // ═══════════════════════════════════════════════════════════════════════════
    console.log("🔄 [useGeoSenseData useEffect TRIGGERED]");
    console.log("  activeCity:", activeCity);
    console.log("  Will fetch NDVI?", activeCity === "mumbai");
    // ═══════════════════════════════════════════════════════════════════════════

    // Only fetch real data for Mumbai (the only city with a live backend)
    if (activeCity !== "mumbai") {
      setZones([]);
      setLiveMunicipalities([]);
      setWaterBodies([]);
      setAqiSurface(null);
      setAqiSurfaceStatus("unavailable");
      setNdviSurface(null);
      setLstSurface(null);
      setWaterHealthSurface(null);
      setCompositeSurface(null);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setAqiSurfaceStatus("loading");

    async function fetchData() {
      // ═══════════════════════════════════════════════════════════════════════════
      // 🔎 FETCH FUNCTION EXECUTION DIAGNOSTIC
      // ═══════════════════════════════════════════════════════════════════════════
      console.log("🔎 [FETCH FUNCTION CALLED]");
      console.log("  activeCity:", activeCity);
      console.log("  About to fetch all Mumbai data including NDVI");
      // ═══════════════════════════════════════════════════════════════════════════

      const fetchWaterHealthSurface = async () => {
        const res = await fetch(getApiUrl("/api/surfaces/water-health/latest"));
        if (res.status === 404) {
          return null;
        }
        if (!res.ok) {
          throw new Error(`Water Health Surface API error: ${res.status}`);
        }
        const data = await res.json();
        setWaterHealthSurface(data);
        return data;
      };

      const fetchCompositeSurface = async () => {
        const res = await fetch(getApiUrl("/api/surfaces/composite/latest"));
        if (res.status === 404) {
          return null;
        }
        if (!res.ok) {
          throw new Error(`Composite Surface API error: ${res.status}`);
        }
        const data = await res.json();
        setCompositeSurface(data);
        return data;
      };

      const fetchAqiSurface = async () => {
        try {
          const response = await fetch(getApiUrl("/api/surfaces/aqi/latest"));
          if (response.status === 404) {
            return { surface: null, status: "unavailable" };
          }
          if (!response.ok) {
            return { surface: null, status: "error" };
          }
          const surface = await response.json();
          if (surface?.available === false) {
            setAqiSurfaceInfo(surface);
            return { surface: null, status: "unavailable" };
          }
          if (!surface?.image_url || !Array.isArray(surface.coordinates)) {
            return { surface: null, status: "error" };
          }
          setAqiSurfaceInfo(surface);
          return { surface, status: "available" };
        } catch (surfaceError) {
          console.warn(
            "[useGeoSenseData] AQI surface unavailable:",
            surfaceError,
          );
          return { surface: null, status: "error" };
        }
      };

      try {
        // ═══════════════════════════════════════════════════════════════════════════
        // NDVI FETCH DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        const ndviUrl = getApiUrl("/api/surfaces/ndvi/latest");
        console.log("🔍 [NDVI FETCH START]");
        console.log("  Exact URL:", ndviUrl);
        console.log("  Timestamp:", new Date().toISOString());
        // ═══════════════════════════════════════════════════════════════════════════

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH FETCH DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        const waterHealthUrl = getApiUrl("/api/surfaces/water-health/latest");
        console.log("🔍 [WATER HEALTH FETCH START]");
        console.log("  Exact URL:", waterHealthUrl);
        console.log("  Timestamp:", new Date().toISOString());
        // ═══════════════════════════════════════════════════════════════════════════

        const [
          metricsRes,
          anomalyRes,
          boundaryRes,
          muniRes,
          waterRes,
          aqiSurfaceResult,
          ndviSurfaceRes,
          lstSurfaceRes,
          waterHealthSurfaceData,
          compositeSurfaceData,
        ] = await Promise.all([
          fetch(getApiUrl("/api/metrics/latest")),
          fetch(getApiUrl("/api/anomalies?days=30&limit=200")),
          fetch(getApiUrl("/api/zones/boundary")),
          fetch(getApiUrl("/api/municipalities/latest")),
          fetch(getApiUrl("/api/water-bodies/latest")),
          fetchAqiSurface(),
          fetch(ndviUrl),
          fetch(getApiUrl("/api/surfaces/lst/latest")),
          fetchWaterHealthSurface(),
          fetchCompositeSurface(),
        ]);

        // ═══════════════════════════════════════════════════════════════════════════
        // NDVI FETCH RESPONSE DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("📡 [NDVI FETCH RESPONSE]");
        console.log("  HTTP Status:", ndviSurfaceRes.status);
        console.log("  response.ok:", ndviSurfaceRes.ok);
        console.log(
          "  Content-Type:",
          ndviSurfaceRes.headers.get("Content-Type"),
        );
        console.log("  Status Text:", ndviSurfaceRes.statusText);
        // ═══════════════════════════════════════════════════════════════════════════

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH FETCH RESPONSE DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("📡 [WATER HEALTH FETCH RESPONSE]");
        console.log(
          "  waterHealthSurfaceData is null?",
          waterHealthSurfaceData === null,
        );
        console.log(
          "  waterHealthSurfaceData is undefined?",
          waterHealthSurfaceData === undefined,
        );
        console.log("  Has data:", !!waterHealthSurfaceData);
        if (waterHealthSurfaceData) {
          console.log("  Has image_url:", !!waterHealthSurfaceData?.image_url);
          console.log(
            "  Has coordinates:",
            !!waterHealthSurfaceData?.coordinates,
          );
          console.log("  Has metric:", !!waterHealthSurfaceData?.metric);
        }
        // ═══════════════════════════════════════════════════════════════════════════

        // Legacy zone endpoints are optional context now (pixel → cell → municipality
        // is the primary flow), so a failure here must not blank the map.
        const safeJson = async (res, fallback) => {
          try {
            return res && res.ok ? await res.json() : fallback;
          } catch {
            return fallback;
          }
        };
        const metrics = await safeJson(metricsRes, []);
        const anomalyData = await safeJson(anomalyRes, []);
        const boundaryData = await safeJson(boundaryRes, null);
        const muniData = await safeJson(muniRes, []);
        const waterData = await safeJson(waterRes, []);
        fetch(getApiUrl("/api/ml/summary"))
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => !cancelled && setMlSummary(d))
          .catch(() => {});
        // ═══════════════════════════════════════════════════════════════════════════
        // NDVI DATA PARSING DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("📦 [NDVI FETCH DATA PARSING]");
        console.log("  ndviSurfaceRes.ok:", ndviSurfaceRes.ok);

        let ndviSurfaceData = null;
        if (ndviSurfaceRes.ok) {
          try {
            ndviSurfaceData = await ndviSurfaceRes.json();
            console.log("  ✅ JSON parse successful");
            console.log(
              "  [NDVI FETCH DATA] Complete response:",
              ndviSurfaceData,
            );
            console.log("  Has image_url:", !!ndviSurfaceData?.image_url);
            console.log("  Has coordinates:", !!ndviSurfaceData?.coordinates);
            console.log("  Has metric:", !!ndviSurfaceData?.metric);
          } catch (parseError) {
            console.error("  ❌ JSON parse failed:", parseError);
            console.error("  Response text:", await ndviSurfaceRes.text());
          }
        } else {
          console.warn(
            "  ⚠️ ndviSurfaceRes.ok is false - no data will be parsed",
          );
          console.warn("  Status:", ndviSurfaceRes.status);
          console.warn("  Trying to read response body anyway...");
          try {
            const errorText = await ndviSurfaceRes.text();
            console.warn("  Response body:", errorText);
          } catch (e) {
            console.error("  Could not read response body:", e);
          }
        }
        // ═══════════════════════════════════════════════════════════════════════════

        const lstSurfaceData = lstSurfaceRes.ok
          ? await lstSurfaceRes.json()
          : null;

        console.log("📡 [LST FETCH RESPONSE]");
        console.log("  HTTP Status:", lstSurfaceRes.status);
        console.log("  response.ok:", lstSurfaceRes.ok);
        console.log(
          "  Content-Type:",
          lstSurfaceRes.headers.get("Content-Type"),
        );
        console.log("  lstSurfaceData:", lstSurfaceData);

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH DATA PARSING DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("📦 [WATER HEALTH FETCH DATA PARSING]");
        console.log(
          "  waterHealthSurfaceData is null:",
          waterHealthSurfaceData === null,
        );
        console.log(
          "  waterHealthSurfaceData is undefined:",
          waterHealthSurfaceData === undefined,
        );

        if (waterHealthSurfaceData === null) {
          console.warn(
            "  ⚠️ Water Health surface is null (404 or no data available) - silently proceeding",
          );
        } else if (waterHealthSurfaceData) {
          console.log("  ✅ Data received from fetchWaterHealthSurface");
          console.log(
            "  [WATER HEALTH FETCH DATA] Complete response:",
            waterHealthSurfaceData,
          );
          console.log("  Has image_url:", !!waterHealthSurfaceData?.image_url);
          console.log(
            "  Has coordinates:",
            !!waterHealthSurfaceData?.coordinates,
          );
          console.log("  Has metric:", !!waterHealthSurfaceData?.metric);
        }
        // ═══════════════════════════════════════════════════════════════════════════

        if (cancelled) return;

        // Build a lookup: zone_id → anomaly info
        const anomalyById = {};
        for (const a of anomalyData) {
          anomalyById[a.locality_id] = a;
        }

        // Build zone objects from the metrics response
        const zoneObjects = metrics.map((m) => {
          const anomaly = anomalyById[m.id] ?? null;
          const isAnomaly = !!anomaly;
          const anomalyScore = anomaly?.anomaly_score ?? null;

          const composite = m.composite ?? null;
          const severity = composite?.score ?? null;

          return {
            // Identifiers
            id: m.id, // backend integer zone_id
            name: m.name,
            ward: m.ward,
            // Polygon geometry from PostGIS (ST_AsGeoJSON)
            geometry: m.geometry ?? null,
            // Coordinates from PostGIS centroid
            coords: [m.longitude, m.latitude],
            // Real measured values (may be null)
            aqi: m.aqi,
            ndvi: m.ndvi,
            lst: m.lst,
            mndwi: m.mndwi,
            ndci: m.ndci,
            turbidity_proxy: m.turbidity_proxy,
            water_extent_m2: m.water_extent_m2,
            water_health_score: m.water_health_score,
            water_health_status: m.water_health_status,
            water_health_observed_at: m.water_health_observed_at,
            aqi_observed_at: m.aqi_observed_at,
            ndvi_observed_at: m.ndvi_observed_at,
            lst_observed_at: m.lst_observed_at,
            source_metadata: m.source_metadata,
            composite,
            pm25: m.pm25,
            pm10: m.pm10,
            no2: m.no2,
            aqi_source_type: m.aqi_source_type,
            aqi_nearest_station_distance_m: m.aqi_nearest_station_distance_m,
            date: m.date,
            // Anomaly from Isolation Forest (not recomputed in React)
            is_anomaly: isAnomaly,
            anomaly_score: anomalyScore,
            // Visual severity comes from the backend Composite; NULL stays NULL.
            severity,
            // Type for color lookup
            type: isAnomaly
              ? "critical"
              : (m.aqi ?? 0) > 200
                ? "high"
                : "moderate",
          };
        });

        setZones(zoneObjects);
        setLiveMunicipalities(muniData);
        setWaterBodies(waterData);
        setAqiSurface(aqiSurfaceResult.surface);
        setAqiSurfaceStatus(aqiSurfaceResult.status);

        // ═══════════════════════════════════════════════════════════════════════════
        // NDVI STATE ASSIGNMENT DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("💾 [NDVI STATE ASSIGNMENT]");
        console.log("  About to call setNdviSurface with:", ndviSurfaceData);
        console.log("  Is null?", ndviSurfaceData === null);
        console.log("  Is undefined?", ndviSurfaceData === undefined);
        console.log("  Truthy?", !!ndviSurfaceData);
        // ═══════════════════════════════════════════════════════════════════════════

        setNdviSurface(ndviSurfaceData);
        setLstSurface(lstSurfaceData);

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH STATE ASSIGNMENT DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        console.log("💾 [WATER HEALTH STATE ASSIGNMENT]");
        console.log(
          "  About to call setWaterHealthSurface with:",
          waterHealthSurfaceData,
        );
        console.log("  Is null?", waterHealthSurfaceData === null);
        console.log("  Is undefined?", waterHealthSurfaceData === undefined);
        console.log("  Truthy?", !!waterHealthSurfaceData);
        // ═══════════════════════════════════════════════════════════════════════════

        setWaterHealthSurface(waterHealthSurfaceData);
        if (compositeSurfaceData) {
          setCompositeSurface(compositeSurfaceData);
        }
        setBoundary(boundaryData);
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          // ═══════════════════════════════════════════════════════════════════════════
          // NDVI FETCH ERROR DIAGNOSTICS
          // ═══════════════════════════════════════════════════════════════════════════
          console.error("❌ [NDVI FETCH ERROR]");
          console.error("  Error message:", err.message);
          console.error("  Error stack:", err.stack);
          console.error("  Full error object:", err);
          // ═══════════════════════════════════════════════════════════════════════════

          console.error("[useGeoSenseData] fetch error:", err);
          setError(err.message || "Backend unavailable");
          setAqiSurfaceStatus("error");
          setLoading(false);
        }
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [activeCity]);

  console.log("📦 [useGeoSenseData RETURN]", {
    hasZones: zones.length,
    aqiSurface: !!aqiSurface,
    aqiSurfaceStatus,
    ndviSurface: !!ndviSurface,
    lstSurface: !!lstSurface,
    waterHealthSurface: !!waterHealthSurface,
    lstSurfaceValue: lstSurface,
  });

  return {
    zones,
    liveMunicipalities,
    waterBodies,
    aqiSurface,
    aqiSurfaceStatus,
    aqiSurfaceInfo,
    mlSummary,
    ndviSurface,
    lstSurface,
    waterHealthSurface,
    compositeSurface,
    boundary,
    loading,
    error,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// useZoneExplanation (point-based)
// GET /api/analysis/point/explain?lon=&lat= → evidence + ML signals + RAG
// citations (+ validated LLM text when a key is configured on the server).
// Name kept for compatibility with existing components.
// ─────────────────────────────────────────────────────────────────────────────
export function useZoneExplanation() {
  const [explanationData, setExplanationData] = useState(null);
  const [explanationLoading, setExplanationLoading] = useState(false);
  const [explanationError, setExplanationError] = useState(null);
  const requestIdRef = useRef(0);

  // llm=false gives the instant evidence-only summary (used for the side panel);
  // Deep Analysis asks again with the AI write-up for the tab being viewed.
  const fetchExplanation = useCallback(async (lon, lat, focus = null, llm = true) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    const requestId = ++requestIdRef.current;
    setExplanationLoading(true);
    setExplanationError(null);
    setExplanationData(null);
    try {
      const res = await fetch(
        getApiUrl(
          `/api/analysis/point/explain?lon=${lon}&lat=${lat}&llm=${llm ? "true" : "false"}` +
            (focus && focus !== "all" ? `&focus=${focus}` : ""),
        ),
      );
      if (requestId !== requestIdRef.current) return;
      if (res.status === 404) {
        setExplanationData({ _unavailable: true });
      } else if (!res.ok) {
        throw new Error(`Explanation API error: ${res.status}`);
      } else {
        setExplanationData(await res.json());
      }
    } catch (err) {
      console.error("[useZoneExplanation] fetch error:", err);
      setExplanationError(err.message || "Explanation unavailable");
      setExplanationData({ _unavailable: true, error: err.message });
    } finally {
      setExplanationLoading(false);
    }
  }, []);

  const clearExplanation = useCallback(() => {
    setExplanationData(null);
    setExplanationError(null);
    setExplanationLoading(false);
  }, []);

  return {
    explanationData,
    explanationLoading,
    explanationError,
    fetchExplanation,
    clearExplanation,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// useHotspots — GeoJSON of ML-flagged 300 m cells for the map overlay
// ─────────────────────────────────────────────────────────────────────────────
export function useHotspots(model) {
  const [hotspots, setHotspots] = useState(null);
  useEffect(() => {
    if (!model) {
      setHotspots(null);
      return;
    }
    let cancelled = false;
    fetch(getApiUrl(`/api/ml/hotspots?model=${model}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => !cancelled && setHotspots(d))
      .catch(() => !cancelled && setHotspots(null));
    return () => {
      cancelled = true;
    };
  }, [model]);
  return hotspots;
}

// ─────────────────────────────────────────────────────────────────────────────
// askAssistant — grounded Q&A (POST /api/assistant/ask)
// ─────────────────────────────────────────────────────────────────────────────
export async function askAssistant(question, lon = null, lat = null, focus = null) {
  const res = await fetch(getApiUrl("/api/assistant/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, lon, lat, focus: focus && focus !== "all" ? focus : null }),
  });
  if (!res.ok) throw new Error(`Assistant error ${res.status}`);
  return res.json();
}

import { useState, useEffect, useCallback, useRef } from "react";
import { getApiUrl } from "../utils/api";

const dlog =
  import.meta.env.VITE_DEBUG_MAP === "1" ? console.log.bind(console) : () => {};

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
  const [provenance, setProvenance] = useState(null);
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
    dlog("🔄 [useGeoSenseData useEffect TRIGGERED]");
    dlog("  activeCity:", activeCity);
    dlog("  Will fetch NDVI?", activeCity === "mumbai");
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

    // The backend can take 10–30 s to start (it loads the AI and data libraries).
    // Wait until it answers instead of giving up on the map layers after one try.
    async function waitForBackend(maxWaitMs = 120000) {
      const started = Date.now();
      while (!cancelled && Date.now() - started < maxWaitMs) {
        try {
          const r = await fetch(getApiUrl("/api/health"), {
            cache: "no-store",
          });
          if (r) return true; // any HTTP answer means the server is up
        } catch {
          /* not up yet */
        }
        await new Promise((res) => setTimeout(res, 2000));
      }
      return false;
    }

    async function fetchData() {
      await waitForBackend();
      if (cancelled) return;
      // ═══════════════════════════════════════════════════════════════════════════
      // 🔎 FETCH FUNCTION EXECUTION DIAGNOSTIC
      // ═══════════════════════════════════════════════════════════════════════════
      dlog("🔎 [FETCH FUNCTION CALLED]");
      dlog("  activeCity:", activeCity);
      dlog("  About to fetch all Mumbai data including NDVI");
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
        dlog("🔍 [NDVI FETCH START]");
        dlog("  Exact URL:", ndviUrl);
        dlog("  Timestamp:", new Date().toISOString());
        // ═══════════════════════════════════════════════════════════════════════════

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH FETCH DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        const waterHealthUrl = getApiUrl("/api/surfaces/water-health/latest");
        dlog("🔍 [WATER HEALTH FETCH START]");
        dlog("  Exact URL:", waterHealthUrl);
        dlog("  Timestamp:", new Date().toISOString());
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
        dlog("📡 [NDVI FETCH RESPONSE]");
        dlog("  HTTP Status:", ndviSurfaceRes.status);
        dlog("  response.ok:", ndviSurfaceRes.ok);
        dlog("  Content-Type:", ndviSurfaceRes.headers.get("Content-Type"));
        dlog("  Status Text:", ndviSurfaceRes.statusText);
        // ═══════════════════════════════════════════════════════════════════════════

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH FETCH RESPONSE DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        dlog("📡 [WATER HEALTH FETCH RESPONSE]");
        dlog(
          "  waterHealthSurfaceData is null?",
          waterHealthSurfaceData === null,
        );
        dlog(
          "  waterHealthSurfaceData is undefined?",
          waterHealthSurfaceData === undefined,
        );
        dlog("  Has data:", !!waterHealthSurfaceData);
        if (waterHealthSurfaceData) {
          dlog("  Has image_url:", !!waterHealthSurfaceData?.image_url);
          dlog("  Has coordinates:", !!waterHealthSurfaceData?.coordinates);
          dlog("  Has metric:", !!waterHealthSurfaceData?.metric);
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
        fetch(getApiUrl("/api/provenance"))
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => !cancelled && setProvenance(d))
          .catch(() => {});
        // ═══════════════════════════════════════════════════════════════════════════
        // NDVI DATA PARSING DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        dlog("📦 [NDVI FETCH DATA PARSING]");
        dlog("  ndviSurfaceRes.ok:", ndviSurfaceRes.ok);

        let ndviSurfaceData = null;
        if (ndviSurfaceRes.ok) {
          try {
            ndviSurfaceData = await ndviSurfaceRes.json();
            dlog("  ✅ JSON parse successful");
            dlog("  [NDVI FETCH DATA] Complete response:", ndviSurfaceData);
            dlog("  Has image_url:", !!ndviSurfaceData?.image_url);
            dlog("  Has coordinates:", !!ndviSurfaceData?.coordinates);
            dlog("  Has metric:", !!ndviSurfaceData?.metric);
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

        dlog("📡 [LST FETCH RESPONSE]");
        dlog("  HTTP Status:", lstSurfaceRes.status);
        dlog("  response.ok:", lstSurfaceRes.ok);
        dlog("  Content-Type:", lstSurfaceRes.headers.get("Content-Type"));
        dlog("  lstSurfaceData:", lstSurfaceData);

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH DATA PARSING DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        dlog("📦 [WATER HEALTH FETCH DATA PARSING]");
        dlog(
          "  waterHealthSurfaceData is null:",
          waterHealthSurfaceData === null,
        );
        dlog(
          "  waterHealthSurfaceData is undefined:",
          waterHealthSurfaceData === undefined,
        );

        if (waterHealthSurfaceData === null) {
          console.warn(
            "  ⚠️ Water Health surface is null (404 or no data available) - silently proceeding",
          );
        } else if (waterHealthSurfaceData) {
          dlog("  ✅ Data received from fetchWaterHealthSurface");
          dlog(
            "  [WATER HEALTH FETCH DATA] Complete response:",
            waterHealthSurfaceData,
          );
          dlog("  Has image_url:", !!waterHealthSurfaceData?.image_url);
          dlog("  Has coordinates:", !!waterHealthSurfaceData?.coordinates);
          dlog("  Has metric:", !!waterHealthSurfaceData?.metric);
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
        dlog("💾 [NDVI STATE ASSIGNMENT]");
        dlog("  About to call setNdviSurface with:", ndviSurfaceData);
        dlog("  Is null?", ndviSurfaceData === null);
        dlog("  Is undefined?", ndviSurfaceData === undefined);
        dlog("  Truthy?", !!ndviSurfaceData);
        // ═══════════════════════════════════════════════════════════════════════════

        setNdviSurface(ndviSurfaceData);
        setLstSurface(lstSurfaceData);

        // ═══════════════════════════════════════════════════════════════════════════
        // WATER HEALTH STATE ASSIGNMENT DIAGNOSTICS
        // ═══════════════════════════════════════════════════════════════════════════
        dlog("💾 [WATER HEALTH STATE ASSIGNMENT]");
        dlog(
          "  About to call setWaterHealthSurface with:",
          waterHealthSurfaceData,
        );
        dlog("  Is null?", waterHealthSurfaceData === null);
        dlog("  Is undefined?", waterHealthSurfaceData === undefined);
        dlog("  Truthy?", !!waterHealthSurfaceData);
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

  // The backend refreshes the AQI layer by itself (and the composite with it). Check every 10 min,
  // or every 30 s while a refresh is running, and swap in the new images when they change, or hide
  // the layer when its readings pass 48 h.
  const aqiKeyRef = useRef(null);
  useEffect(() => {
    if (!activeCity) return undefined;
    let stop = false;
    let timer = null;
    const check = async () => {
      let next = 10 * 60 * 1000;
      try {
        const r = await fetch(getApiUrl("/api/surfaces/aqi/latest"));
        if (r.ok) {
          const s = await r.json();
          if (stop) return;
          if (s?.refresh?.running) next = 30 * 1000;
          const key = s?.available ? s.image_url : `off:${s?.status}`;
          if (aqiKeyRef.current !== null && key !== aqiKeyRef.current) {
            setAqiSurfaceInfo(s);
            if (s?.available && s.image_url && Array.isArray(s.coordinates)) {
              setAqiSurface(s);
              setAqiSurfaceStatus("available");
              // the composite's air part was rebuilt from the new AQI
              const c = await fetch(
                getApiUrl("/api/surfaces/composite/latest"),
              );
              if (c.ok && !stop) setCompositeSurface(await c.json());
            } else {
              setAqiSurface(null);
              setAqiSurfaceStatus("unavailable");
            }
          } else if (!s?.available) {
            setAqiSurfaceInfo(s); // keep the "expired / refreshing" message current
          }
          aqiKeyRef.current = key;
        }
      } catch {
        // backend not reachable right now: try again later
      }
      if (!stop) timer = setTimeout(check, next);
    };
    timer = setTimeout(check, 30 * 1000);
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [activeCity]);

  dlog("📦 [useGeoSenseData RETURN]", {
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
    provenance,
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
  // true while the AI plain-words summary is being written; the evidence stays on screen meanwhile
  const [aiPending, setAiPending] = useState(false);
  const requestIdRef = useRef(0);
  // the request currently on its way: asking again for the same thing joins it instead of
  // restarting it (opening Deep Analysis right after a click used to blank the panel and start
  // the same request over, so it looked like it loaded, vanished and loaded again)
  const inflightRef = useRef(null);

  // llm=false gives the instant evidence-only write-up (~0.1 s). llm=true adds the AI summary,
  // which can take several seconds — pass { keep: true } so the panel keeps showing the evidence
  // while it is written, instead of blanking. Returns the response (or null).
  const fetchExplanation = useCallback(
    async (lon, lat, focus = null, llm = true, opts = {}) => {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
      const key = `${lon}|${lat}|${focus || ""}|${llm ? 1 : 0}`;
      if (
        inflightRef.current?.key === key &&
        inflightRef.current.requestId === requestIdRef.current
      ) {
        return inflightRef.current.promise;
      }
      const keep = !!opts.keep;
      const requestId = ++requestIdRef.current;
      const promise = run(requestId, keep);
      inflightRef.current = { key, requestId, promise };
      return promise;

      async function run(requestId, keep) {
        if (keep) {
          if (llm) setAiPending(true);
        } else {
          setExplanationLoading(true);
          setExplanationData(null);
          setAiPending(false);
        }
        setExplanationError(null);
        try {
          const res = await fetch(
            getApiUrl(
              `/api/analysis/point/explain?lon=${lon}&lat=${lat}&llm=${llm ? "true" : "false"}` +
                (focus && focus !== "all" ? `&focus=${focus}` : ""),
            ),
          );
          if (requestId !== requestIdRef.current) return null;
          if (res.status === 404) {
            setExplanationData({ _unavailable: true });
            return null;
          }
          if (!res.ok) throw new Error(`Explanation API error: ${res.status}`);
          const data = await res.json();
          if (requestId !== requestIdRef.current) return null;
          setExplanationData(data);
          return data;
        } catch (err) {
          console.error("[useZoneExplanation] fetch error:", err);
          if (requestId !== requestIdRef.current) return null;
          setExplanationError(err.message || "Explanation unavailable");
          // with keep, the evidence already on screen stays; only a fresh load shows "unavailable"
          if (!keep)
            setExplanationData({ _unavailable: true, error: err.message });
          return null;
        } finally {
          if (requestId === requestIdRef.current) {
            setExplanationLoading(false);
            setAiPending(false);
          }
          if (inflightRef.current?.requestId === requestId)
            inflightRef.current = null;
        }
      }
    },
    [],
  );

  const clearExplanation = useCallback(() => {
    requestIdRef.current += 1;
    inflightRef.current = null;
    setExplanationData(null);
    setExplanationError(null);
    setExplanationLoading(false);
    setAiPending(false);
  }, []);

  return {
    explanationData,
    explanationLoading,
    explanationError,
    aiPending,
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
export async function askAssistant(
  question,
  lon = null,
  lat = null,
  focus = null,
  intent = null,
) {
  const res = await fetch(getApiUrl("/api/assistant/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      lon,
      lat,
      focus: focus && focus !== "all" ? focus : null,
      intent,
    }),
  });
  if (res.status === 429 || res.status === 422) {
    // rate limit or a request the server's validation rejected: show the server's reason as the answer
    const body = await res.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : "Please rephrase your question (it was not accepted).";
    return { answer: detail, citations: [], mode: "guardrail", warnings: [] };
  }
  if (!res.ok) throw new Error(`Assistant error ${res.status}`);
  return res.json();
}

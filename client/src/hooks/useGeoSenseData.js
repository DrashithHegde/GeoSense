import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch, setApiCity } from "../utils/api";

// ─────────────────────────────────────────────────────────────────────────────
// useGeoSenseData(activeCity)
// Loads everything the map needs for one city: the study-region boundary, its municipalities,
// and the latest NDVI / LST / Water Health / AQI / composite surfaces, plus the ML summary and
// data provenance. A layer the city does not have yet stays null (never borrowed from another
// city, never made up).
// ─────────────────────────────────────────────────────────────────────────────
export function useGeoSenseData(activeCity) {
  const [liveMunicipalities, setLiveMunicipalities] = useState([]);
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
    // clear the previous city's layers first, so nothing from another city stays on screen
    setLiveMunicipalities([]);
    setAqiSurface(null);
    setAqiSurfaceInfo(null);
    setMlSummary(null);
    setProvenance(null);
    setNdviSurface(null);
    setLstSurface(null);
    setWaterHealthSurface(null);
    setCompositeSurface(null);
    setBoundary(null);
    setError(null);
    if (!activeCity) {
      setAqiSurfaceStatus("idle");
      setLoading(false);
      return undefined;
    }
    setApiCity(activeCity);

    let cancelled = false;
    setLoading(true);
    setAqiSurfaceStatus("loading");
    const q = `city=${encodeURIComponent(activeCity)}`;

    // A hosted backend can take up to a minute to wake up (free tiers sleep when idle).
    // Wait until it answers instead of giving up on the map layers after one try.
    async function waitForBackend(maxWaitMs = 120000) {
      const started = Date.now();
      while (!cancelled && Date.now() - started < maxWaitMs) {
        try {
          const r = await apiFetch(`/api/health?${q}`, { cache: "no-store" });
          if (r) return true; // any HTTP answer means the server is up
        } catch {
          /* not up yet */
        }
        await new Promise((res) => setTimeout(res, 2000));
      }
      return false;
    }

    // JSON of a layer endpoint; null when the city does not have that layer (404) or on error
    const getJson = async (path) => {
      try {
        const res = await apiFetch(`${path}${path.includes("?") ? "&" : "?"}${q}`);
        return res.ok ? await res.json() : null;
      } catch {
        return null;
      }
    };

    async function fetchData() {
      await waitForBackend();
      if (cancelled) return;
      try {
        const [boundaryData, muniData, aqi, ndvi, lst, wh, composite] = await Promise.all([
          getJson("/api/zones/boundary"),
          getJson("/api/municipalities/latest"),
          getJson("/api/surfaces/aqi/latest"),
          getJson("/api/surfaces/ndvi/latest"),
          getJson("/api/surfaces/lst/latest"),
          getJson("/api/surfaces/water-health/latest"),
          getJson("/api/surfaces/composite/latest"),
        ]);
        if (cancelled) return;
        setBoundary(boundaryData);
        setLiveMunicipalities(Array.isArray(muniData) ? muniData : []);
        setAqiSurfaceInfo(aqi);
        if (aqi?.available && aqi.image_url && Array.isArray(aqi.coordinates)) {
          setAqiSurface(aqi);
          setAqiSurfaceStatus("available");
        } else {
          setAqiSurfaceStatus(aqi ? "unavailable" : "error");
        }
        setNdviSurface(ndvi);
        setLstSurface(lst);
        setWaterHealthSurface(wh);
        setCompositeSurface(composite);
        setLoading(false);
        getJson("/api/ml/summary").then((d) => !cancelled && setMlSummary(d));
        getJson("/api/provenance").then((d) => !cancelled && setProvenance(d));
      } catch (err) {
        if (!cancelled) {
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

  // The backend refreshes each city's AQI layer by itself (and the composite with it). Check every
  // 10 min, or every 30 s while a refresh is running, and swap in the new images when they change,
  // or hide the layer when its readings pass 48 h.
  const aqiKeyRef = useRef(null);
  useEffect(() => {
    aqiKeyRef.current = null;
    if (!activeCity) return undefined;
    let stop = false;
    let timer = null;
    const q = `city=${encodeURIComponent(activeCity)}`;
    const check = async () => {
      let next = 10 * 60 * 1000;
      try {
        const r = await apiFetch(`/api/surfaces/aqi/latest?${q}`);
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
              const c = await apiFetch(`/api/surfaces/composite/latest?${q}`);
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

  return {
    liveMunicipalities,
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
  const fetchExplanation = useCallback(async (lon, lat, focus = null, llm = true, opts = {}) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
    const key = `${lon}|${lat}|${focus || ""}|${llm ? 1 : 0}`;
    if (inflightRef.current?.key === key && inflightRef.current.requestId === requestIdRef.current) {
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
        const res = await apiFetch(
          `/api/analysis/point/explain?lon=${lon}&lat=${lat}&llm=${llm ? "true" : "false"}` +
            (focus && focus !== "all" ? `&focus=${focus}` : ""),
        );
        if (requestId !== requestIdRef.current) return null;
        if (res.status === 404) {
          const body = await res.json().catch(() => ({}));
          setExplanationData({ _unavailable: true, reason: typeof body.detail === "string" ? body.detail : null });
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
        if (!keep) setExplanationData({ _unavailable: true, error: err.message });
        return null;
      } finally {
        if (requestId === requestIdRef.current) {
          setExplanationLoading(false);
          setAiPending(false);
        }
        if (inflightRef.current?.requestId === requestId) inflightRef.current = null;
      }
    }
  }, []);

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
// askAssistant — grounded Q&A (POST /api/assistant/ask)
// ─────────────────────────────────────────────────────────────────────────────
export async function askAssistant(question, lon = null, lat = null, focus = null, intent = null) {
  const res = await apiFetch("/api/assistant/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, lon, lat, focus: focus && focus !== "all" ? focus : null, intent }),
  });
  if (res.status === 429 || res.status === 422) {
    // rate limit or a request the server's validation rejected: show the server's reason as the answer
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : "Please rephrase your question (it was not accepted).";
    return { answer: detail, citations: [], mode: "guardrail", warnings: [] };
  }
  if (!res.ok) throw new Error(`Assistant error ${res.status}`);
  return res.json();
}

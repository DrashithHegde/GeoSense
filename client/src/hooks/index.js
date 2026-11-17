import { useState, useEffect, useRef, useCallback } from "react";
import { formatUTCTime, buildMunicipalitiesGeoJSON } from "../utils/helpers";
import { CITY_CONFIG } from "../constants/cities";
import { MAPBOX_TOKEN } from "../constants/layers";
import { apiFetch, getApiUrl } from "../utils/api";
import mapboxgl from "mapbox-gl";

// Map diagnostics are off unless VITE_DEBUG_MAP=1 is set in client/.env — logging on every
// render and every paint slowed the app noticeably (App re-renders every second for the clock).
const DEBUG_MAP = import.meta.env.VITE_DEBUG_MAP === "1";
const dlog = DEBUG_MAP ? console.log.bind(console) : () => {};
const dgroup = DEBUG_MAP ? console.group.bind(console) : () => {};
const dgroupEnd = DEBUG_MAP ? console.groupEnd.bind(console) : () => {};

// The style is ready for setLayoutProperty/addLayer once its JSON has loaded — even while image
// sources are still downloading. map.isStyleLoaded() stays false during those downloads, which
// made a layer toggle silently do nothing until the next map click.
// Run fn now if the style is ready, otherwise as soon as it is (style.load or the next idle,
// whichever comes first). Errors are logged instead of silently leaving a layer missing.
// Returns a cleanup for useEffect.
function runWhenStyleReady(map, fn, name = "layer") {
  const run = () => {
    try {
      fn();
    } catch (err) {
      console.error(`[GeoSense map] ${name} failed:`, err);
    }
  };
  if (styleReady(map)) {
    run();
    return undefined;
  }
  let done = false;
  const once = () => {
    if (done || !styleReady(map)) return;
    done = true;
    map.off("style.load", once);
    map.off("idle", once);
    run();
  };
  map.on("style.load", once);
  map.on("idle", once);
  return () => {
    map.off("style.load", once);
    map.off("idle", once);
  };
}

function styleReady(map) {
  if (!map) return false;
  if (map.style && typeof map.style._loaded === "boolean") return map.style._loaded;
  try {
    return !!map.getStyle();
  } catch (_) {
    return false;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// DIAGNOSTIC STARTUP CONFIRMATION
// ═══════════════════════════════════════════════════════════════════════════
dlog("═".repeat(80));
dlog("[GEOSENSE DIAGNOSTICS ACTIVE] - hooks/index.js loaded");
dlog("Timestamp:", new Date().toISOString());
dlog("MAPBOX_TOKEN available:", !!MAPBOX_TOKEN);
dlog("═".repeat(80));
// ═══════════════════════════════════════════════════════════════════════════

const CENTER_EPSILON = 0.0005;
const ZOOM_EPSILON = 0.02;
const INDIA_CENTER = [79.0, 22.2];
const INDIA_ZOOM = 3.65;
const MAP_STYLE = "mapbox://styles/mapbox/dark-v11";
const SELECTED_MUNI_HEIGHT = 800;

const MUNI_SOURCE = "mmr-municipalities";
const MUNI_EXTRUDE = "muni-extrusion";
const MUNI_OUTLINE = "muni-outline";
const MUNI_LABEL = "muni-label";
const AQI_HALO_SOURCE = "aqi-halo";
const AQI_HALO_LAYER = "aqi-halo-raster";
const AQI_GLOW_SOURCE = "aqi-glow";
const AQI_GLOW_LAYER = "aqi-glow-raster";
const AQI_SURFACE_SOURCE = "aqi-surface";
const AQI_SURFACE_LAYER = "aqi-surface-raster";
const AQI_RASTER_OPACITY = 0.96;
// Same layer strengths for every heatmap, matched to Water Health (halo · glow · sharp).
const HALO_OPACITY = 0.8;
const GLOW_OPACITY = 0.6;
const SHARP_OPACITY = 0.96;
const NDVI_HALO_SOURCE = "ndvi-halo";
const NDVI_HALO_LAYER = "ndvi-halo-raster";
const NDVI_GLOW_SOURCE = "ndvi-glow";
const NDVI_GLOW_LAYER = "ndvi-glow-raster";
const NDVI_SURFACE_SOURCE = "ndvi-surface";
const NDVI_SURFACE_LAYER = "ndvi-surface-raster";
const WATER_HEALTH_HALO_SOURCE = "water-health-halo";
const WATER_HEALTH_HALO_LAYER = "water-health-halo-raster";
const WATER_HEALTH_GLOW_SOURCE = "water-health-glow";
const WATER_HEALTH_GLOW_LAYER = "water-health-glow-raster";
const WATER_HEALTH_SURFACE_SOURCE = "water-health-surface";
const WATER_HEALTH_SURFACE_LAYER = "water-health-surface-raster";
const LST_HALO_SOURCE = "lst-halo";
const LST_HALO_LAYER = "lst-halo-raster";
const LST_GLOW_SOURCE = "lst-glow";
const LST_GLOW_LAYER = "lst-glow-raster";
const LST_SURFACE_SOURCE = "lst-surface";
const LST_SURFACE_LAYER = "lst-surface-raster";
const COMPOSITE_GLOW_SOURCE = "composite-glow";
const COMPOSITE_GLOW_LAYER = "composite-glow-raster";
const COMPOSITE_SURFACE_SOURCE = "composite-surface";
const COMPOSITE_SURFACE_LAYER = "composite-surface-raster";
const COMPOSITE_HALO_SOURCE = "composite-halo";
const COMPOSITE_HALO_LAYER = "composite-halo-raster";
function getMetricProp(layerId) {
  switch (layerId) {
    case "aqi":
      return "aqi_norm";
    case "ndvi":
      return "ndvi_norm";
    case "lst":
      return "lst_norm";
    case "water_health":
      return "water_norm";
    case "all":
      return "composite_norm";
    default:
      return "composite_norm";
  }
}

function buildFillColorExpression(layerId) {
  const prop = getMetricProp(layerId);
  const ramps = {
    aqi_norm: [
      [0.0, "#ffffff"],
      [0.1, "#f0f0f0"],
      [0.2, "#c8c8c8"],
      [0.4, "#969696"],
      [0.6, "#646464"],
      [1.0, "#323232"],
    ],
    ndvi_norm: [
      [0.0, "#006400"],
      [0.2, "#32CD32"],
      [0.4, "#FFFF00"],
      [0.6, "#D2B48C"],
      [0.8, "#8B4513"],
      [1.0, "#5C4033"],
    ],
    lst_norm: [
      [0.0, "#00BFFF"],
      [0.25, "#1dd1a1"],
      [0.45, "#ffd32a"],
      [0.65, "#ff8c00"],
      [0.85, "#ff3b3b"],
      [1.0, "#8B0000"],
    ],
    composite_norm: [
      [0.0, "#00E400"],
      [0.2, "#00E400"],
      [0.45, "#FFFF00"],
      [0.6, "#FF7E00"],
      [0.8, "#FF0000"],
      [0.9, "#8F3F97"],
      [1.0, "#7E0023"],
    ],
  };
  const stops = ramps[prop] || ramps["composite_norm"];
  return [
    "case",
    ["==", ["get", prop], null],
    "#1a1a2e",
    [
      "interpolate",
      ["linear"],
      ["get", prop],
      ...stops.flatMap(([s, c]) => [s, c]),
    ],
  ];
}

function getPrimaryLayerId(activeLayers) {
  if (!activeLayers) return "all";
  if (activeLayers.all) return "all";
  return Object.entries(activeLayers).find(([, v]) => v)?.[0] || "all";
}

function shouldSkipFlyTo(map, targetCenter, targetZoom) {
  if (
    !map ||
    !Array.isArray(targetCenter) ||
    targetCenter.length < 2 ||
    typeof targetZoom !== "number"
  )
    return false;
  try {
    const c = map.getCenter();
    return (
      Math.abs(c.lng - targetCenter[0]) < CENTER_EPSILON &&
      Math.abs(c.lat - targetCenter[1]) < CENTER_EPSILON &&
      Math.abs(map.getZoom() - targetZoom) < ZOOM_EPSILON
    );
  } catch (_) {
    return false;
  }
}

export function useClock() {
  const [time, setTime] = useState(formatUTCTime());
  useEffect(() => {
    const id = setInterval(() => setTime(formatUTCTime()), 1000);
    return () => clearInterval(id);
  }, []);
  return time;
}

export function useToast(duration = 1500) {
  const [message, setMessage] = useState(null);
  const [phase, setPhase] = useState("in");
  const timerRef = useRef(null);
  const show = useCallback(
    (msg) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      setMessage(msg);
      setPhase("in");
      timerRef.current = setTimeout(() => {
        setPhase("out");
        setTimeout(() => setMessage(null), 350);
      }, duration);
    },
    [duration],
  );
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );
  return { message, phase, show };
}

export function useIntro() {
  const [phase, setPhase] = useState("in");
  const [panelsVisible, setPanelsVisible] = useState(false);
  useEffect(() => {
    const t1 = setTimeout(() => setPhase("out"), 2200);
    const t2 = setTimeout(() => {
      setPhase("done");
      setPanelsVisible(true);
    }, 3100);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);
  return { phase, panelsVisible };
}

export function useMapbox({
  containerRef,
  activeCity,
  activeLayers,
  onZoneClick,
  onPointAnalysis,
  liveMunicipalities = [],
  aqiSurface = null,
  ndviSurface = null,
  lstSurface = null,
  waterHealthSurface = null,
  compositeSurface = null,
  boundary = null,
  hotspots = null,
  markerPoint = null,
  onPointPending = null,
}) {
  // ═══════════════════════════════════════════════════════════════════════════
  // DIAGNOSTIC: Hook execution confirmation
  // ═══════════════════════════════════════════════════════════════════════════
  dlog("🚨🚨🚨 [CACHE BUSTER v2.0 - Sep 20 2026 08:50] 🚨🚨🚨");
  dlog("[GEOSENSE DIAGNOSTICS] useMapbox hook called");
  dlog("  activeCity:", activeCity);
  dlog("  activeLayers:", activeLayers);
  dlog("  aqiSurface:", !!aqiSurface);
  dlog("  ndviSurface:", !!ndviSurface);
  dlog("  lstSurface:", !!lstSurface);
  dlog("  waterHealthSurface:", !!waterHealthSurface);
  dlog("  compositeSurface:", !!compositeSurface);
  dlog("  lstSurface actual value:", lstSurface);
  dlog("🚨🚨🚨 END CACHE BUSTER 🚨🚨🚨");
  // ═══════════════════════════════════════════════════════════════════════════

  const mapRef = useRef(null);
  const onZoneClickRef = useRef(onZoneClick);
  const onPointAnalysisRef = useRef(onPointAnalysis);
  const onPointPendingRef = useRef(onPointPending);
  const pointSeqRef = useRef(0);
  const pointAbortRef = useRef(null);
  const pendingCityRef = useRef(null);
  const activeLayersRef = useRef(activeLayers);
  const liveMunisRef = useRef(liveMunicipalities);
  const selectedMuniRef = useRef(null);
  const aqiSurfaceRef = useRef(aqiSurface);
  const ndviSurfaceRef = useRef(ndviSurface);
  const lstSurfaceRef = useRef(lstSurface);
  const waterHealthSurfaceRef = useRef(waterHealthSurface);
  const compositeSurfaceRef = useRef(compositeSurface);
  useEffect(() => {
    onZoneClickRef.current = onZoneClick;
  }, [onZoneClick]);
  useEffect(() => {
    onPointAnalysisRef.current = onPointAnalysis;
    onPointPendingRef.current = onPointPending;
  }, [onPointAnalysis]);
  useEffect(() => {
    activeLayersRef.current = activeLayers;
  }, [activeLayers]);

  useEffect(() => {
    liveMunisRef.current = liveMunicipalities;
    const map = mapRef.current;
    if (!map || !styleReady(map)) return;
    const sync = () => {
      const src = map.getSource(MUNI_SOURCE);
      if (src) src.setData(buildMunicipalitiesGeoJSON(liveMunisRef.current));
      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
        !!compositeSurfaceRef.current,
      );
    };
    if (styleReady(map)) sync();
    else map.once("idle", sync);
  }, [liveMunicipalities]);


  // ── ML hotspot overlay: glowing heatmap + crisp cell markers ───────────────
  const hotspotsRef = useRef(hotspots);
  useEffect(() => {
    hotspotsRef.current = hotspots;
    const map = mapRef.current;
    if (!map) return;
    const SRC = "geosense-ml-hotspots";
    const HEAT = "geosense-ml-hotspots-heat";
    const DOTS = "geosense-ml-hotspots-dots";
    const COLORS = {
      isolation_forest_cell_v2: "#ff3bd4",
      xgboost_lst_residual_v1: "#ff5a1f",
      water_health_robust_z_v1: "#ffd23c",
    };
    const sync = () => {
      const data = hotspotsRef.current;
      const empty = { type: "FeatureCollection", features: [] };
      if (!map.getSource(SRC)) {
        map.addSource(SRC, { type: "geojson", data: data || empty });
        map.addLayer({
          id: HEAT,
          type: "heatmap",
          source: SRC,
          maxzoom: 16,
          paint: {
            "heatmap-weight": ["get", "intensity"],
            "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 9, 0.6, 14, 1.6],
            "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 8, 12, 22, 15, 48],
            "heatmap-opacity": 0.75,
            "heatmap-color": [
              "interpolate", ["linear"], ["heatmap-density"],
              0, "rgba(0,0,0,0)",
              0.2, "rgba(120,30,160,0.35)",
              0.45, "rgba(255,59,212,0.6)",
              0.7, "rgba(255,120,40,0.8)",
              1, "rgba(255,240,180,0.95)",
            ],
          },
        });
        map.addLayer({
          id: DOTS,
          type: "circle",
          source: SRC,
          minzoom: 11.5,
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 11.5, 2.5, 15, 7],
            "circle-color": "#ffffff",
            "circle-opacity": 0.85,
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#ff3bd4",
          },
        });
      } else {
        map.getSource(SRC).setData(data || empty);
      }
      const color = COLORS[data?.model] || "#ff3bd4";
      if (map.getLayer(DOTS)) map.setPaintProperty(DOTS, "circle-stroke-color", color);
      const vis = data && data.features?.length ? "visible" : "none";
      [HEAT, DOTS].forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", vis));
      [HEAT, DOTS].forEach((id) => map.getLayer(id) && map.moveLayer(id));
    };
    if (styleReady(map)) sync();
    else map.once("idle", sync);
  }, [hotspots]);

  useEffect(() => {
    aqiSurfaceRef.current = aqiSurface;
    const map = mapRef.current;
    if (!map || !aqiSurface) return;

    function syncAQI() {
      const coords = aqiSurface.coordinates;
      const beforeId = map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined;

      // HALO
      if (aqiSurface.halo_url) {
        const haloOpts = { url: getApiUrl(aqiSurface.halo_url), coordinates: coords };
        const s = map.getSource(AQI_HALO_SOURCE);
        if (s) s.updateImage(haloOpts);
        else map.addSource(AQI_HALO_SOURCE, { type: "image", ...haloOpts });
        if (!map.getLayer(AQI_HALO_LAYER)) {
          map.addLayer(
            {
              id: AQI_HALO_LAYER,
              type: "raster",
              source: AQI_HALO_SOURCE,
              layout: { visibility: "none" },
              paint: { "raster-opacity": HALO_OPACITY, "raster-fade-duration": 500, "raster-resampling": "linear" },
            },
            beforeId,
          );
        }
      }

      // GLOW
      if (aqiSurface.glow_url) {
        const glowOpts = { url: getApiUrl(aqiSurface.glow_url), coordinates: coords };
        const s = map.getSource(AQI_GLOW_SOURCE);
        if (s) s.updateImage(glowOpts);
        else map.addSource(AQI_GLOW_SOURCE, { type: "image", ...glowOpts });
        if (!map.getLayer(AQI_GLOW_LAYER)) {
          map.addLayer(
            {
              id: AQI_GLOW_LAYER,
              type: "raster",
              source: AQI_GLOW_SOURCE,
              layout: { visibility: "none" },
              paint: { "raster-opacity": GLOW_OPACITY, "raster-fade-duration": 380, "raster-resampling": "linear" },
            },
            beforeId,
          );
        }
      }

      // SHARP
      const sharpOpts = { url: getApiUrl(aqiSurface.sharp_url || aqiSurface.image_url), coordinates: coords };
      const s = map.getSource(AQI_SURFACE_SOURCE);
      if (s) s.updateImage(sharpOpts);
      else map.addSource(AQI_SURFACE_SOURCE, { type: "image", ...sharpOpts });
      if (!map.getLayer(AQI_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: AQI_SURFACE_LAYER,
            type: "raster",
            source: AQI_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: { "raster-opacity": AQI_RASTER_OPACITY, "raster-fade-duration": 300, "raster-resampling": "linear" },
          },
          beforeId,
        );
      }

      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        true,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
        !!compositeSurfaceRef.current,
      );
    }

    return runWhenStyleReady(map, syncAQI, "syncAQI");
  }, [aqiSurface]);

  useEffect(() => {
    ndviSurfaceRef.current = ndviSurface;
    const map = mapRef.current;

    if (!map || !ndviSurface) return;

    function syncNDVI() {
      const coords = ndviSurface.coordinates;
      const beforeId = map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined;

      // ---- HALO (widest soft glow, bottom of stack) ----
      if (ndviSurface.halo_url) {
        const haloOpts = {
          url: getApiUrl(ndviSurface.halo_url),
          coordinates: coords,
        };
        const s = map.getSource(NDVI_HALO_SOURCE);
        if (s) s.updateImage(haloOpts);
        else map.addSource(NDVI_HALO_SOURCE, { type: "image", ...haloOpts });
        if (!map.getLayer(NDVI_HALO_LAYER)) {
          map.addLayer(
            {
              id: NDVI_HALO_LAYER,
              type: "raster",
              source: NDVI_HALO_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": HALO_OPACITY,
                "raster-fade-duration": 500,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // ---- GLOW (medium blur, middle of stack) ----
      if (ndviSurface.glow_url) {
        const glowOpts = {
          url: getApiUrl(ndviSurface.glow_url),
          coordinates: coords,
        };
        const s = map.getSource(NDVI_GLOW_SOURCE);
        if (s) s.updateImage(glowOpts);
        else map.addSource(NDVI_GLOW_SOURCE, { type: "image", ...glowOpts });
        if (!map.getLayer(NDVI_GLOW_LAYER)) {
          map.addLayer(
            {
              id: NDVI_GLOW_LAYER,
              type: "raster",
              source: NDVI_GLOW_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": GLOW_OPACITY,
                "raster-fade-duration": 380,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // ---- SHARP (pixel-exact colour, top of surface stack) ----
      const sharpOpts = {
        url: getApiUrl(ndviSurface.sharp_url || ndviSurface.image_url),
        coordinates: coords,
      };
      const existingSource = map.getSource(NDVI_SURFACE_SOURCE);
      if (existingSource) existingSource.updateImage(sharpOpts);
      else map.addSource(NDVI_SURFACE_SOURCE, { type: "image", ...sharpOpts });

      if (!map.getLayer(NDVI_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: NDVI_SURFACE_LAYER,
            type: "raster",
            source: NDVI_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": SHARP_OPACITY,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          beforeId,
        );
      }

      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        true,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
        !!compositeSurfaceRef.current,
      );
    }

    return runWhenStyleReady(map, syncNDVI, "syncNDVI");
  }, [ndviSurface]);

  useEffect(() => {
    lstSurfaceRef.current = lstSurface;
    const map = mapRef.current;

    // Need both map and data. Style structure readiness is checked inside syncLST.
    if (!map || !lstSurface) return;

    function syncLST() {
      // Called only after style is confirmed ready (style.load has fired).

      // Halo layer (wide soft glow, like Water Health)
      if (lstSurface.halo_url) {
        const haloOpts = { url: getApiUrl(lstSurface.halo_url), coordinates: lstSurface.coordinates };
        const hs = map.getSource(LST_HALO_SOURCE);
        if (hs) hs.updateImage(haloOpts);
        else map.addSource(LST_HALO_SOURCE, { type: "image", ...haloOpts });
        if (!map.getLayer(LST_HALO_LAYER)) {
          map.addLayer(
            {
              id: LST_HALO_LAYER,
              type: "raster",
              source: LST_HALO_SOURCE,
              layout: { visibility: "none" },
              paint: { "raster-opacity": HALO_OPACITY, "raster-fade-duration": 500, "raster-resampling": "linear" },
            },
            map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined,
          );
        }
      }

      // Glow layer (subtle hot-pixel emission effect)
      const glowImageOptions = {
        url: getApiUrl(lstSurface.glow_url),
        coordinates: lstSurface.coordinates,
      };
      const existingGlowSource = map.getSource(LST_GLOW_SOURCE);
      if (existingGlowSource) {
        existingGlowSource.updateImage(glowImageOptions);
      } else {
        map.addSource(LST_GLOW_SOURCE, { type: "image", ...glowImageOptions });
      }
      if (!map.getLayer(LST_GLOW_LAYER)) {
        map.addLayer(
          {
            id: LST_GLOW_LAYER,
            type: "raster",
            source: LST_GLOW_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": GLOW_OPACITY,
              "raster-fade-duration": 400,
              "raster-resampling": "linear",
            },
          },
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined,
        );
      }

      // Sharp layer (main thermal surface)
      const sharpImageOptions = {
        url: getApiUrl(lstSurface.image_url),
        coordinates: lstSurface.coordinates,
      };
      const existingSharpSource = map.getSource(LST_SURFACE_SOURCE);
      if (existingSharpSource) {
        existingSharpSource.updateImage(sharpImageOptions);
      } else {
        map.addSource(LST_SURFACE_SOURCE, {
          type: "image",
          ...sharpImageOptions,
        });
      }
      if (!map.getLayer(LST_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: LST_SURFACE_LAYER,
            type: "raster",
            source: LST_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": SHARP_OPACITY,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined,
        );
      }

      // Sync visibility to current layer state
      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        true,
        !!waterHealthSurfaceRef.current,
        !!compositeSurfaceRef.current,
      );
    }

    // Probe whether style.load has already fired
    return runWhenStyleReady(map, syncLST, "syncLST");
  }, [lstSurface]);

  useEffect(() => {
    waterHealthSurfaceRef.current = waterHealthSurface;
    const map = mapRef.current;

    if (!map || !waterHealthSurface) return;

    function syncWaterHealth() {
      const coords =
        waterHealthSurface.coordinates || waterHealthSurface.mapbox_coordinates;
      const beforeId = map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined;

      // HALO (widest soft glow — bottom of stack)
      if (waterHealthSurface.halo_url) {
        const haloOpts = {
          url: getApiUrl(waterHealthSurface.halo_url),
          coordinates: coords,
        };
        const s = map.getSource(WATER_HEALTH_HALO_SOURCE);
        if (s) s.updateImage(haloOpts);
        else
          map.addSource(WATER_HEALTH_HALO_SOURCE, {
            type: "image",
            ...haloOpts,
          });
        if (!map.getLayer(WATER_HEALTH_HALO_LAYER)) {
          map.addLayer(
            {
              id: WATER_HEALTH_HALO_LAYER,
              type: "raster",
              source: WATER_HEALTH_HALO_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": 0.8,
                "raster-fade-duration": 500,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // GLOW (medium blur — middle)
      if (waterHealthSurface.glow_url) {
        const glowOpts = {
          url: getApiUrl(waterHealthSurface.glow_url),
          coordinates: coords,
        };
        const existingGlowSource = map.getSource(WATER_HEALTH_GLOW_SOURCE);
        if (existingGlowSource) {
          existingGlowSource.updateImage(glowOpts);
        } else {
          map.addSource(WATER_HEALTH_GLOW_SOURCE, {
            type: "image",
            ...glowOpts,
          });
        }
        if (!map.getLayer(WATER_HEALTH_GLOW_LAYER)) {
          map.addLayer(
            {
              id: WATER_HEALTH_GLOW_LAYER,
              type: "raster",
              source: WATER_HEALTH_GLOW_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": 0.6,
                "raster-fade-duration": 400,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // SHARP (pixel-exact — top of surface stack, above halo+glow)
      const sharpOpts = {
        url: getApiUrl(
          waterHealthSurface.sharp_url || waterHealthSurface.image_url,
        ),
        coordinates: coords,
      };
      const existingSharpSource = map.getSource(WATER_HEALTH_SURFACE_SOURCE);
      if (existingSharpSource) {
        existingSharpSource.updateImage(sharpOpts);
      } else {
        map.addSource(WATER_HEALTH_SURFACE_SOURCE, {
          type: "image",
          ...sharpOpts,
        });
      }
      if (!map.getLayer(WATER_HEALTH_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: WATER_HEALTH_SURFACE_LAYER,
            type: "raster",
            source: WATER_HEALTH_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": 0.96,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          beforeId,
        );
      }

      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        true,
        !!compositeSurfaceRef.current,
      );
    }

    return runWhenStyleReady(map, syncWaterHealth, "syncWaterHealth");
  }, [waterHealthSurface]);

  useEffect(() => {
    compositeSurfaceRef.current = compositeSurface;
    const map = mapRef.current;

    if (!map || !compositeSurface) return;

    function syncComposite() {
      const coords =
        compositeSurface.coordinates || compositeSurface.mapbox_coordinates;
      const beforeId = map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined;

      // HALO (widest soft glow — bottom of stack)
      if (compositeSurface.halo_url) {
        const haloOpts = {
          url: getApiUrl(compositeSurface.halo_url),
          coordinates: coords,
        };
        const s = map.getSource(COMPOSITE_HALO_SOURCE);
        if (s) s.updateImage(haloOpts);
        else
          map.addSource(COMPOSITE_HALO_SOURCE, {
            type: "image",
            ...haloOpts,
          });
        if (!map.getLayer(COMPOSITE_HALO_LAYER)) {
          map.addLayer(
            {
              id: COMPOSITE_HALO_LAYER,
              type: "raster",
              source: COMPOSITE_HALO_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": 0.8,
                "raster-fade-duration": 500,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // GLOW (medium blur — middle)
      if (compositeSurface.glow_url) {
        const glowOpts = {
          url: getApiUrl(compositeSurface.glow_url),
          coordinates: coords,
        };
        const existingGlowSource = map.getSource(COMPOSITE_GLOW_SOURCE);
        if (existingGlowSource) {
          existingGlowSource.updateImage(glowOpts);
        } else {
          map.addSource(COMPOSITE_GLOW_SOURCE, {
            type: "image",
            ...glowOpts,
          });
        }
        if (!map.getLayer(COMPOSITE_GLOW_LAYER)) {
          map.addLayer(
            {
              id: COMPOSITE_GLOW_LAYER,
              type: "raster",
              source: COMPOSITE_GLOW_SOURCE,
              layout: { visibility: "none" },
              paint: {
                "raster-opacity": 0.6,
                "raster-fade-duration": 400,
                "raster-resampling": "linear",
              },
            },
            beforeId,
          );
        }
      }

      // SHARP (pixel-exact — top of surface stack, above halo+glow)
      const sharpOpts = {
        url: getApiUrl(
          compositeSurface.sharp_url || compositeSurface.image_url,
        ),
        coordinates: coords,
      };
      const existingSharpSource = map.getSource(COMPOSITE_SURFACE_SOURCE);
      if (existingSharpSource) {
        existingSharpSource.updateImage(sharpOpts);
      } else {
        map.addSource(COMPOSITE_SURFACE_SOURCE, {
          type: "image",
          ...sharpOpts,
        });
      }
      if (!map.getLayer(COMPOSITE_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: COMPOSITE_SURFACE_LAYER,
            type: "raster",
            source: COMPOSITE_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": 0.96,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          beforeId,
        );
      }

      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
        true, // composite
      );
    }

    return runWhenStyleReady(map, syncComposite, "syncComposite");
  }, [compositeSurface]);

  useEffect(() => {
    // ═══════════════════════════════════════════════════════════════════════════
    // DIAGNOSTIC: Map initialization useEffect triggered
    // ═══════════════════════════════════════════════════════════════════════════
    dlog(
      "[GEOSENSE DIAGNOSTICS] Map initialization useEffect triggered",
    );
    dlog("  containerRef.current exists:", !!containerRef.current);
    dlog("  mapRef.current exists:", !!mapRef.current);
    dlog(
      "🚨 [MAP DIAGNOSTIC VERSION] guard check: containerRef.current =",
      !!containerRef.current,
      "| mapRef.current =",
      !!mapRef.current,
    );
    // ═══════════════════════════════════════════════════════════════════════════

    if (!containerRef.current || mapRef.current) return;
    const token = MAPBOX_TOKEN;

    // ═══════════════════════════════════════════════════════════════════════════
    // MAPBOX TOKEN DIAGNOSTIC
    // ═══════════════════════════════════════════════════════════════════════════
    dgroup("🗺️ MAPBOX CONFIGURATION");
    dlog("Token exists:", !!token);
    dlog("Token starts with 'pk.':", token?.startsWith("pk."));
    dlog("Token length:", token?.length);
    dlog("Token first 20 chars:", token?.substring(0, 20));
    dlog("Map style:", MAP_STYLE);
    dgroupEnd();
    // ═══════════════════════════════════════════════════════════════════════════

    if (!token || token === "YOUR_MAPBOX_TOKEN_HERE") return;
    mapboxgl.accessToken = token;

    dlog(
      "🚨 [MAP DIAGNOSTIC VERSION] lifecycle instrumentation build ALPHA-1",
    );

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: INDIA_CENTER,
      zoom: INDIA_ZOOM,
      pitch: 0,
      bearing: 0,
      projection: "mercator",
      antialias: true,
      attributionControl: false,
      logoPosition: "bottom-right",
    });

    dlog(
      "🚨 [MAP DIAGNOSTIC VERSION] map constructor completed ALPHA-1",
    );
    mapRef.current = map;

    // ═══════════════════════════════════════════════════════════════════════════
    // [MAP LIFECYCLE] Map instance identity + lifecycle event diagnostics
    // ═══════════════════════════════════════════════════════════════════════════
    const mapInstanceId = "map-" + Date.now();
    map._diagnosticId = mapInstanceId;
    dgroup("🏗️ [MAP LIFECYCLE] new mapboxgl.Map() created");
    dlog("  mapInstanceId:", mapInstanceId);
    dlog("  Timestamp:", new Date().toISOString());
    dlog("  map.isStyleLoaded() at creation:", map.isStyleLoaded());
    dlog(
      "  map.getStyle() at creation: (not called — throws in v3 before style.load)",
    );
    dgroupEnd();

    map.on("styledata", () => {
      dlog("📋 [MAP LIFECYCLE] 'styledata' event");
      dlog("  mapInstanceId:", map._diagnosticId);
      dlog("  Timestamp:", new Date().toISOString());
      dlog("  map.isStyleLoaded():", map.isStyleLoaded());
      dlog("  map.getStyle() exists:", !!map.getStyle());
    });

    map.on("style.load", () => {
      dgroup("🎨 [MAP LIFECYCLE] 'style.load' event fired");
      dlog("  mapInstanceId:", map._diagnosticId);
      dlog("  Timestamp:", new Date().toISOString());
      dlog("  map.isStyleLoaded():", map.isStyleLoaded());
      dlog("  map.getStyle() exists:", !!map.getStyle());
      dgroupEnd();
    });

    map.on("load", () => {
      dgroup("✅ [MAP LIFECYCLE] 'load' event fired");
      dlog("  mapInstanceId:", map._diagnosticId);
      dlog("  Timestamp:", new Date().toISOString());
      dlog("  map.isStyleLoaded():", map.isStyleLoaded());
      dlog("  map.getStyle() exists:", !!map.getStyle());
      dgroupEnd();
    });

    map.on("idle", () => {
      dlog("💤 [MAP LIFECYCLE] 'idle' event fired");
      dlog("  mapInstanceId:", map._diagnosticId);
      dlog("  Timestamp:", new Date().toISOString());
      dlog("  map.isStyleLoaded():", map.isStyleLoaded());
    });
    // ═══════════════════════════════════════════════════════════════════════════

    // ═══════════════════════════════════════════════════════════════════════════
    // TEMPORARY MAPBOX ERROR LISTENER FOR NDVI DIAGNOSTICS
    // ═══════════════════════════════════════════════════════════════════════════
    let mapboxErrorCount = 0;
    let errorUrlsSeen = new Set();

    map.on("error", (e) => {
      mapboxErrorCount++;

      // ═══════════════════════════════════════════════════════════════════════════
      // [MAPBOX ERROR] Check if NDVI-related
      // ═══════════════════════════════════════════════════════════════════════════
      const isNdviRelated =
        e.sourceId === NDVI_SURFACE_SOURCE ||
        (e.error?.message && e.error.message.includes("ndvi")) ||
        (e.error?.url && e.error.url.includes("ndvi"));

      if (isNdviRelated) {
        dgroup("🔴 [MAPBOX ERROR] NDVI-RELATED ERROR DETECTED");
        console.error("  Timestamp:", new Date().toISOString());
        console.error("  Error count:", mapboxErrorCount);
        console.error("  sourceId:", e.sourceId);
        console.error("  error.message:", e.error?.message);
        console.error("  error.url:", e.error?.url);
        console.error("  Full error object:", e.error);
        console.error("  Full event:", e);
        dgroupEnd();
      }
      // ═══════════════════════════════════════════════════════════════════════════

      // Extract URL
      const errorMsg = e.error?.message || e.error?.toString() || "";
      const urlMatch = errorMsg.match(/https?:\/\/[^\s]+/);
      const failedUrl = urlMatch ? urlMatch[0] : "unknown";

      // Only log detailed info for first few errors and unique URLs (unless NDVI-related, always log those)
      const shouldLogDetailed =
        isNdviRelated || mapboxErrorCount <= 5 || !errorUrlsSeen.has(failedUrl);

      if (shouldLogDetailed) {
        dgroup(
          `❌ Mapbox Error #${mapboxErrorCount}${isNdviRelated ? " [NDVI]" : ""}`,
        );
        console.error("11. Mapbox error event:", e);
        console.error("    Error object:", e.error);
        if (e.error && e.error.message) {
          console.error("    Error message:", e.error.message);
        }
        if (e.error && e.error.url) {
          console.error("    Failed URL:", e.error.url);
        }
        if (e.sourceId) {
          console.error("    Source ID:", e.sourceId);
        }
        if (e.tile) {
          console.error("    Tile:", e.tile);
        }

        // Try to extract URL from error message
        if (urlMatch) {
          console.error("    Extracted URL from message:", urlMatch[0]);
          errorUrlsSeen.add(failedUrl);

          // Determine resource type from URL
          if (urlMatch[0].includes("/v4/")) {
            console.error(
              "    Resource type: Mapbox Vector Tile (v4 API - LEGACY)",
            );
            console.error(
              "    ⚠️ WARNING: v4 API is deprecated. Modern Mapbox uses vector tiles v2.",
            );
          } else if (urlMatch[0].includes("/sprites/")) {
            console.error("    Resource type: Sprite");
          } else if (
            urlMatch[0].includes("/fonts/") ||
            urlMatch[0].includes("/glyphs/")
          ) {
            console.error("    Resource type: Font/Glyph");
          } else if (urlMatch[0].includes("/styles/")) {
            console.error("    Resource type: Style");
          } else if (
            urlMatch[0].includes("/surface-assets/") ||
            urlMatch[0].includes("ndvi")
          ) {
            console.error("    Resource type: NDVI Surface Asset");
          }
        }

        console.error("    Timestamp:", new Date().toISOString());
        dgroupEnd();
      }

      // Summary every 25 errors
      if (mapboxErrorCount % 25 === 0) {
        console.warn(
          `📊 Mapbox Error Summary: ${mapboxErrorCount} total errors`,
        );
        console.warn(`    Unique URLs failing: ${errorUrlsSeen.size}`);
        console.warn(`    URLs:`, Array.from(errorUrlsSeen));
      }
    });

    map.on("data", (e) => {
      if (e.sourceId === NDVI_SURFACE_SOURCE && e.isSourceLoaded) {
        dgroup(
          "✅ [NDVI DATA EVENT] NDVI source data loaded successfully",
        );
        dlog("  Timestamp:", new Date().toISOString());
        dlog("  sourceId:", e.sourceId);
        dlog("  isSourceLoaded:", e.isSourceLoaded);
        dlog("  dataType:", e.dataType);
        dgroupEnd();
      }
    });

    map.on("sourcedata", (e) => {
      if (e.sourceId === NDVI_SURFACE_SOURCE) {
        dgroup("📡 [NDVI SOURCEDATA EVENT]");
        dlog("  Timestamp:", new Date().toISOString());
        dlog("  isSourceLoaded:", e.isSourceLoaded);
        dlog("  dataType:", e.dataType);
        dlog("  tile:", e.tile);
        dlog("  coord:", e.coord);
        dgroupEnd();
      }
    });
    // ═══════════════════════════════════════════════════════════════════════════

    const handleMuniClick = (e) => {
      const feature = e.features?.[0];
      if (feature) {
        const muniId = feature.properties.id;
        selectedMuniRef.current = muniId;
        applyMunicipalityPaint(
          map,
          activeLayersRef.current,
          muniId,
          !!aqiSurfaceRef.current,
          !!ndviSurfaceRef.current,
          !!lstSurfaceRef.current,
          !!waterHealthSurfaceRef.current,
          !!compositeSurfaceRef.current,
        );
      }
      // The point itself is fetched by handleCanvasClick, which fires for every map click
      // (including this one). Fetching here too made two requests per click, and the second
      // answer re-ran the click handling (closing Deep Analysis if it had just been opened).
      map.stop();
      map.easeTo({
        center: [e.lngLat.lng, e.lngLat.lat],
        zoom: Math.max(map.getZoom(), 12.5),
        pitch: 52,
        bearing: -10,
        duration: 1100,
        essential: true,
      });
    };

    // Canvas-wide click handler: works when the user clicks ANYWHERE on the map
    // (transparent water, open land, anywhere) — not just on top of MUNI_EXTRUDE.
    // Use raw e.lngLat as the exact scientific-sample location.
    // Deduplicates with handleMuniClick via a small tolerance check on the same tick.
    let _lastCanvasClickKey = "";
    let _lastCanvasClickAt = 0;
    const handleCanvasClick = (e) => {
      const lng = e.lngLat.lng;
      const lat = e.lngLat.lat;
      const key = `${lng.toFixed(5)}_${lat.toFixed(5)}`;
      const now = Date.now();
      // If the muni-extrusion click handler already ran within 50ms at the
      // same ~coordinate, skip to avoid double-fetching.
      if (key === _lastCanvasClickKey && now - _lastCanvasClickAt < 100) return;
      _lastCanvasClickKey = key;
      _lastCanvasClickAt = now;
      _handlePointAnalyze(map, lng, lat);
    };

    // Only the latest click counts: a newer click cancels the older request, and a late answer
    // for an older click is ignored, so the panel and pin never jump back to a previous spot.
    function _handlePointAnalyze(map, lng, lat) {
      const seq = ++pointSeqRef.current;
      pointAbortRef.current?.abort();
      const ctrl = new AbortController();
      pointAbortRef.current = ctrl;
      onPointPendingRef.current?.(lng, lat);   // pin drops immediately, before the answer
      apiFetch(`/api/analysis/point?lon=${lng}&lat=${lat}`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((data) => {
          if (seq !== pointSeqRef.current) return;
          const pixel = data.pixel || {};
          const cell = data.cell || {};
          const muni = data.municipality || {};
          const cellMetrics = cell.metrics || {};

          const pixelNdvi =
            pixel.ndvi && !pixel.ndvi.nodata ? pixel.ndvi.value : null;
          const pixelLstC =
            pixel.lst && !pixel.lst.nodata ? pixel.lst.value_c : null;
          const pixelAqi =
            pixel.aqi && !pixel.aqi.nodata ? pixel.aqi.value : null;
          const pixelWater =
            pixel.water_health && !pixel.water_health.nodata
              ? pixel.water_health.value
              : null;

          const cellNdvi = cellMetrics.ndvi ?? null;
          const cellLst = cellMetrics.lst ?? null;
          const cellAqi = cellMetrics.aqi ?? null;
          const cellWater = cellMetrics.water_health_score ?? null;

          // a real place name (e.g. "Powai, Mumbai") from the backend; the municipality otherwise
          const displayName =
            data?.place?.label || muni.name || cell.cell_code || "Selected location";

          const syntheticZone = {
            id: cell.id ?? `pt-${lng.toFixed(4)}-${lat.toFixed(4)}`,
            name: displayName,
            coords: [lng, lat],
            aqi: cellAqi,
            ndvi: cellNdvi,
            lst: cellLst,
            water_health_score: cellWater,
            pixelLST: pixel.lst,
            pixelNDVI: pixel.ndvi,
            pixelAQI: pixel.aqi,
            pixelWaterHealth: pixel.water_health,
            pixelWaterHealthValue: pixelWater,
            cell_id: cell.id,
            cell_code: cell.cell_code,
            resolution_m: cell.resolution_m,
            cell_anomaly: cell.anomaly,
            cell_centroid: cell.centroid,
            cell_observed_at: cellMetrics.observed_at,
            municipality_name: muni.name,
            municipality_id: muni.id,
            composite: {
              score:
                pixel.composite && !pixel.composite.nodata
                  ? Math.round(pixel.composite.value * 100)
                  : null,
            },
            pointAnalysis: data,
          };

          if (muni.id) {
            selectedMuniRef.current = muni.id;
            applyMunicipalityPaint(
              map,
              activeLayersRef.current,
              muni.id,
              !!aqiSurfaceRef.current,
              !!ndviSurfaceRef.current,
              !!lstSurfaceRef.current,
              !!waterHealthSurfaceRef.current,
              !!compositeSurfaceRef.current,
            );
          }

          if (onPointAnalysisRef.current) {
            onPointAnalysisRef.current(syntheticZone, data);
          } else {
            onZoneClickRef.current?.(syntheticZone);
          }
        })
        .catch((err) => {
          if (err?.name === "AbortError" || seq !== pointSeqRef.current) return;
          console.error("Point analysis failed", err);
          const fallbackZone = {
            id: `pt-${lng.toFixed(4)}-${lat.toFixed(4)}`,
            name: "Selected location",
            coords: [lng, lat],
          };
          onZoneClickRef.current?.(fallbackZone);
        });
    }

    let hoveredId = null;
    const handleMouseMove = (e) => {
      if (e.features.length > 0) {
        if (hoveredId !== null)
          map.setFeatureState(
            { source: MUNI_SOURCE, id: hoveredId },
            { hovered: false },
          );
        hoveredId = e.features[0].id;
        map.setFeatureState(
          { source: MUNI_SOURCE, id: hoveredId },
          { hovered: true },
        );
      }
    };
    const handleMouseLeave = () => {
      if (hoveredId !== null) {
        map.setFeatureState(
          { source: MUNI_SOURCE, id: hoveredId },
          { hovered: false },
        );
        hoveredId = null;
      }
      map.getCanvas().style.cursor = "";
    };
    const handleMouseEnter = () => {
      map.getCanvas().style.cursor = "crosshair";
    };

    const setupLayers = () => {
      // ═══════════════════════════════════════════════════════════════════════════
      // [MAP LIFECYCLE] setupLayers() entry
      // ═══════════════════════════════════════════════════════════════════════════
      dgroup("🔧 [MAP LIFECYCLE] setupLayers() called");
      dlog("  mapInstanceId:", map._diagnosticId);
      dlog("  Timestamp:", new Date().toISOString());
      dlog("  map.isStyleLoaded() BEFORE:", map.isStyleLoaded());
      dlog("  map.getStyle() exists:", !!map.getStyle());
      // ═══════════════════════════════════════════════════════════════════════════

      const style = map.getStyle();
      if (style?.layers) {
        style.layers.forEach((layer) => {
          const iconImage = layer.layout?.["icon-image"];
          if (iconImage && JSON.stringify(iconImage).includes("in-state")) {
            try {
              map.setLayoutProperty(layer.id, "icon-image", undefined);
            } catch (_) {}
          }
        });
      }

      if (!map.getSource(MUNI_SOURCE))
        map.addSource(MUNI_SOURCE, {
          type: "geojson",
          data: buildMunicipalitiesGeoJSON(liveMunisRef.current),
          promoteId: "id",
        });

      // Create MUNI_EXTRUDE layer FIRST so raster layers can reference it with beforeId
      if (!map.getLayer(MUNI_EXTRUDE)) {
        map.addLayer({
          id: MUNI_EXTRUDE,
          type: "fill-extrusion",
          source: MUNI_SOURCE,
          paint: {
            "fill-extrusion-color": "#2a2a3a",
            "fill-extrusion-height": 0,
            "fill-extrusion-base": 0,
            "fill-extrusion-opacity": 0.85,
          },
        });
      }

      // Now add AQI raster layer positioned before MUNI_EXTRUDE.
      // NDVI source/layer are owned exclusively by the ndviSurface useEffect (syncNDVI).
      if (aqiSurfaceRef.current && !map.getSource(AQI_SURFACE_SOURCE)) {
        map.addSource(AQI_SURFACE_SOURCE, {
          type: "image",
          url: getApiUrl(aqiSurfaceRef.current.image_url),
          coordinates: aqiSurfaceRef.current.coordinates,
        });
      }
      if (
        map.getSource(AQI_SURFACE_SOURCE) &&
        !map.getLayer(AQI_SURFACE_LAYER)
      ) {
        map.addLayer(
          {
            id: AQI_SURFACE_LAYER,
            type: "raster",
            source: AQI_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": AQI_RASTER_OPACITY,
              "raster-fade-duration": 0,
              "raster-resampling": "linear",
            },
          },
          MUNI_EXTRUDE,
        );
      }
      if (!map.getLayer(MUNI_OUTLINE)) {
        map.addLayer({
          id: MUNI_OUTLINE,
          type: "line",
          source: MUNI_SOURCE,
          // Start all boundaries very subdued — applyMunicipalityPaint raises
          // the selected boundary on click.
          paint: {
            "line-color": "#00e5ff",
            "line-width": 0.5,
            "line-opacity": 0.18,
          },
        });
      }
      // No MUNI_LABEL layer: the Mapbox dark-v11 basemap already supplies
      // place/city labels for Mumbai and its districts.  Adding a GeoSense
      // symbol layer on top produces duplicate labels at every municipality.

      map.off("click", MUNI_EXTRUDE, handleMuniClick);
      map.off("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.off("mouseleave", MUNI_EXTRUDE, handleMouseLeave);
      map.off("mousemove", MUNI_EXTRUDE, handleMouseMove);
      map.off("click", handleCanvasClick);
      map.on("click", MUNI_EXTRUDE, handleMuniClick);
      map.on("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.on("mouseleave", MUNI_EXTRUDE, handleMouseLeave);
      map.on("mousemove", MUNI_EXTRUDE, handleMouseMove);
      map.on("click", handleCanvasClick);

      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
      );
      if (pendingCityRef.current) {
        const p = pendingCityRef.current;
        pendingCityRef.current = null;
        flyToCity(map, p);
      }

      // ═══════════════════════════════════════════════════════════════════════════
      // [MAP LIFECYCLE] setupLayers() exit
      // ═══════════════════════════════════════════════════════════════════════════
      dlog(
        "  map.isStyleLoaded() AFTER setupLayers:",
        map.isStyleLoaded(),
      );
      dlog("  map.getStyle() exists AFTER:", !!map.getStyle());
      dlog(
        "  ndviSurfaceRef.current at setupLayers time:",
        !!ndviSurfaceRef.current,
      );
      dgroupEnd();
      // ═══════════════════════════════════════════════════════════════════════════
    };

    map.on("style.load", setupLayers);
    return () => {
      map.off("style.load", setupLayers);
      map.off("click", MUNI_EXTRUDE, handleMuniClick);
      map.off("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.off("mouseleave", MUNI_EXTRUDE, handleMouseLeave);
      map.off("mousemove", MUNI_EXTRUDE, handleMouseMove);
      map.off("click", handleCanvasClick);

      // ═══════════════════════════════════════════════════════════════════════════
      // TEMPORARY CLEANUP DIAGNOSTIC
      // ═══════════════════════════════════════════════════════════════════════════
      dlog("12. React cleanup - checking for layer/source removal");
      dlog(
        "    NDVI layer exists before cleanup:",
        !!map.getLayer(NDVI_SURFACE_LAYER),
      );
      dlog(
        "    NDVI source exists before cleanup:",
        !!map.getSource(NDVI_SURFACE_SOURCE),
      );
      // ═══════════════════════════════════════════════════════════════════════════

      map.remove();
      mapRef.current = null;
    };
  }, [containerRef]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!activeCity) {
      const map = mapRef.current;
      if (map)
        map.easeTo({
          center: INDIA_CENTER,
          zoom: INDIA_ZOOM,
          pitch: 0,
          bearing: 0,
          duration: 1400,
          essential: true,
        });
      return;
    }
    const city = CITY_CONFIG[activeCity];
    if (!city) return;
    const map = mapRef.current;
    if (map && styleReady(map)) {
      flyToCity(map, city);
    } else {
      pendingCityRef.current = city;
      let attempts = 0;
      const timer = setInterval(() => {
        attempts++;
        const m = mapRef.current;
        if (m && styleReady(m)) {
          clearInterval(timer);
          pendingCityRef.current = null;
          flyToCity(m, city);
        } else if (attempts > 20) clearInterval(timer);
      }, 200);
      return () => clearInterval(timer);
    }
  }, [activeCity]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const paint = () =>
      applyMunicipalityPaint(
        map,
        activeLayers,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        !!lstSurfaceRef.current,
        !!waterHealthSurfaceRef.current,
        !!compositeSurfaceRef.current,
      );
    return runWhenStyleReady(map, paint, "layer switch");
  }, [activeLayers]);

  // ── Click marker: bright white location pin with the place name floating above (game-style).
  // Removed when the side panel closes.
  const clickMarkerRef = useRef(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const lng = markerPoint?.longitude;
    const lat = markerPoint?.latitude;
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
      clickMarkerRef.current?.remove();
      clickMarkerRef.current = null;
      return;
    }
    let el = clickMarkerRef.current?.getElement();
    if (!clickMarkerRef.current) {
      el = document.createElement("div");
      el.className = "geo-marker";
      el.innerHTML =
        '<div class="geo-marker-float">' +
        '<div class="geo-marker-label"><span class="geo-marker-label-text"></span></div>' +
        '<div class="geo-marker-pin"><span class="geo-marker-core"></span></div>' +
        '</div><div class="geo-marker-shadow"></div>';
      clickMarkerRef.current = new mapboxgl.Marker({ element: el, anchor: "bottom" });
    }
    const label = String(markerPoint?.label || "Selected location").split(",")[0].trim();
    const textEl = el.querySelector(".geo-marker-label-text");
    if (textEl) textEl.textContent = label.toUpperCase();
    el.setAttribute("aria-label", `Selected location: ${label}`);
    // replay the drop-in animation only for a new spot (not when the name fills in)
    const spot = `${lng.toFixed(6)},${lat.toFixed(6)}`;
    if (el.dataset.spot !== spot) {
      el.dataset.spot = spot;
      el.classList.remove("geo-marker-drop");
      void el.offsetWidth;
      el.classList.add("geo-marker-drop");
    }
    el.classList.toggle("geo-marker-pending", !!markerPoint?.pending);
    clickMarkerRef.current.setLngLat([lng, lat]).addTo(map);
  }, [markerPoint?.longitude, markerPoint?.latitude, markerPoint?.label, markerPoint?.pending]);

  return mapRef;
}

function flyToCity(map, city) {
  const targetZoom = city.zoom ?? 10.5;
  if (shouldSkipFlyTo(map, city.center, targetZoom)) return;
  map.stop();
  map.flyTo({
    center: city.center,
    zoom: targetZoom,
    pitch: 50,
    bearing: -10,
    duration: 2600,
    essential: true,
    curve: 1.6,
    speed: 0.65,
  });
}

function applyMunicipalityPaint(
  map,
  activeLayers,
  selectedMuniId,
  hasAqiSurface = false,
  hasNdviSurface = false,
  hasLstSurface = false,
  hasWaterHealthSurface = false,
  hasCompositeSurface = false,
) {
  if (!map || !styleReady(map)) return;
  const layerId = getPrimaryLayerId(activeLayers);
  const isWaterMode = layerId === "water_health";
  const isAqiSurfaceMode = layerId === "aqi" && hasAqiSurface;
  const isNdviSurfaceMode = layerId === "ndvi" && hasNdviSurface;
  const isLstSurfaceMode = layerId === "lst" && hasLstSurface;
  const isWaterHealthSurfaceMode =
    layerId === "water_health" && hasWaterHealthSurface;
  const isCompositeSurfaceMode =
    layerId === "all" && hasCompositeSurface;
  const isSurfaceMode =
    isAqiSurfaceMode ||
    isNdviSurfaceMode ||
    isLstSurfaceMode ||
    isWaterHealthSurfaceMode ||
    isCompositeSurfaceMode;

  const isEnvMetricPendingNoRasterYet =
    (layerId === "aqi" && !hasAqiSurface) ||
    (layerId === "ndvi" && !hasNdviSurface) ||
    (layerId === "water_health" && !hasWaterHealthSurface) ||
    (layerId === "all" && !hasCompositeSurface);

  const isFLIRMode = isLstSurfaceMode;

  dlog("🔍 [SURFACE MODE DETECTION]");
  dlog("  layerId:", layerId);
  dlog("  hasLstSurface:", hasLstSurface);
  dlog("  hasWaterHealthSurface:", hasWaterHealthSurface);
  dlog("  isLstSurfaceMode:", isLstSurfaceMode);
  dlog("  isNdviSurfaceMode:", isNdviSurfaceMode);
  dlog("  isWaterHealthSurfaceMode:", isWaterHealthSurfaceMode);
  dlog(
    "  isEnvMetricPendingNoRasterYet:",
    isEnvMetricPendingNoRasterYet,
  );
  dlog("  isFLIRMode:", isFLIRMode);

  if (DEBUG_MAP && (layerId === "ndvi" || isNdviSurfaceMode)) {
    dgroup("🔍 NDVI RUNTIME DIAGNOSTIC");
    dlog("1. activeLayers:", JSON.stringify(activeLayers, null, 2));
    dlog("2. getPrimaryLayerId(activeLayers):", layerId);
    dlog("3. hasNdviSurface:", hasNdviSurface);
    dlog("4. isNdviSurfaceMode:", isNdviSurfaceMode);

    const ndviSource = map.getSource(NDVI_SURFACE_SOURCE);
    const ndviLayer = map.getLayer(NDVI_SURFACE_LAYER);
    dlog("5. map.getSource(NDVI_SURFACE_SOURCE) exists:", !!ndviSource);
    if (ndviSource) {
      dlog("   Source type:", ndviSource.type);
      try {
        const sourceData = map.getSource(NDVI_SURFACE_SOURCE).serialize();
        dlog("   Source URL:", sourceData.url);
        dlog("   Source coordinates:", sourceData.coordinates);
      } catch (e) {
        dlog("   Could not serialize source:", e.message);
      }
    }

    dlog("6. map.getLayer(NDVI_SURFACE_LAYER) exists:", !!ndviLayer);
    if (ndviLayer) {
      dlog("   Layer type:", ndviLayer.type);
      dlog("   Layer source:", ndviLayer.source);
      try {
        const visibility = map.getLayoutProperty(
          NDVI_SURFACE_LAYER,
          "visibility",
        );
        const opacity = map.getPaintProperty(
          NDVI_SURFACE_LAYER,
          "raster-opacity",
        );
        dlog("7. NDVI layer visibility:", visibility);
        dlog("8. NDVI raster opacity:", opacity);
      } catch (e) {
        dlog("   Could not get layer properties:", e.message);
      }
    }

    const allLayers = map.getStyle().layers.map((l) => l.id);
    const ndviIndex = allLayers.indexOf(NDVI_SURFACE_LAYER);
    const muniIndex = allLayers.indexOf(MUNI_EXTRUDE);
    dlog("   Layer stack positions:");
    dlog("   - NDVI_SURFACE_LAYER at index:", ndviIndex);
    dlog("   - MUNI_EXTRUDE at index:", muniIndex);
    dlog(
      "   - Layer order (NDVI before MUNI?):",
      ndviIndex !== -1 && muniIndex !== -1 && ndviIndex < muniIndex,
    );

    dgroupEnd();
  }

  if (map.getLayer(AQI_HALO_LAYER)) {
    map.setLayoutProperty(
      AQI_HALO_LAYER,
      "visibility",
      isAqiSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(AQI_GLOW_LAYER)) {
    map.setLayoutProperty(
      AQI_GLOW_LAYER,
      "visibility",
      isAqiSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(AQI_SURFACE_LAYER)) {
    map.setLayoutProperty(
      AQI_SURFACE_LAYER,
      "visibility",
      isAqiSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(NDVI_HALO_LAYER)) {
    map.setLayoutProperty(
      NDVI_HALO_LAYER,
      "visibility",
      isNdviSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(NDVI_GLOW_LAYER)) {
    map.setLayoutProperty(
      NDVI_GLOW_LAYER,
      "visibility",
      isNdviSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(NDVI_SURFACE_LAYER)) {
    map.setLayoutProperty(
      NDVI_SURFACE_LAYER,
      "visibility",
      isNdviSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(LST_HALO_LAYER)) {
    map.setLayoutProperty(LST_HALO_LAYER, "visibility", isLstSurfaceMode ? "visible" : "none");
  }
  if (map.getLayer(LST_GLOW_LAYER)) {
    map.setLayoutProperty(
      LST_GLOW_LAYER,
      "visibility",
      isLstSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(LST_SURFACE_LAYER)) {
    map.setLayoutProperty(
      LST_SURFACE_LAYER,
      "visibility",
      isLstSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(WATER_HEALTH_HALO_LAYER)) {
    map.setLayoutProperty(
      WATER_HEALTH_HALO_LAYER,
      "visibility",
      isWaterHealthSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(WATER_HEALTH_GLOW_LAYER)) {
    map.setLayoutProperty(
      WATER_HEALTH_GLOW_LAYER,
      "visibility",
      isWaterHealthSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(WATER_HEALTH_SURFACE_LAYER)) {
    map.setLayoutProperty(
      WATER_HEALTH_SURFACE_LAYER,
      "visibility",
      isWaterHealthSurfaceMode ? "visible" : "none",
    );
  }

  if (map.getLayer(COMPOSITE_HALO_LAYER)) {
    map.setLayoutProperty(
      COMPOSITE_HALO_LAYER,
      "visibility",
      isCompositeSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(COMPOSITE_GLOW_LAYER)) {
    map.setLayoutProperty(
      COMPOSITE_GLOW_LAYER,
      "visibility",
      isCompositeSurfaceMode ? "visible" : "none",
    );
  }
  if (map.getLayer(COMPOSITE_SURFACE_LAYER)) {
    map.setLayoutProperty(
      COMPOSITE_SURFACE_LAYER,
      "visibility",
      isCompositeSurfaceMode ? "visible" : "none",
    );
  }

  if (map.getLayer(MUNI_EXTRUDE)) {
    if (isFLIRMode) {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "visible");
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-opacity", 0.0);
    } else {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "visible");
      let colorExpr;
      let opacityExpr;
      const isCompositeMode = layerId === "all" || layerId === "composite";
      if (isEnvMetricPendingNoRasterYet) {
        colorExpr = "#0e0e1a";
        opacityExpr = 0.06;
      } else {
        colorExpr =
          isWaterMode || isSurfaceMode || isCompositeMode
            ? "#0e0e1a"
            : buildFillColorExpression(layerId);
        opacityExpr = isSurfaceMode || isCompositeMode ? 0.0 : isWaterMode ? 0.12 : 0.82;
      }
      const heightExpr =
        selectedMuniId != null && !isWaterMode
          ? [
              "case",
              ["==", ["get", "id"], selectedMuniId],
              SELECTED_MUNI_HEIGHT,
              0,
            ]
          : 0;
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-color", colorExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-opacity", opacityExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-height", heightExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-base", 0);
    }
  }

  if (map.getLayer(MUNI_OUTLINE)) {
    const isCompositeView = layerId === "all" || layerId === "composite";
    
    if (isCompositeView) {
      map.setLayoutProperty(MUNI_OUTLINE, "visibility", "visible");
      
      const outlineColor = "#ffffff";
      const outlineWidth = 1.5;
      const outlineOpacity = 0.8;
      
      map.setPaintProperty(MUNI_OUTLINE, "line-color", outlineColor);
      map.setPaintProperty(MUNI_OUTLINE, "line-width", outlineWidth);
      map.setPaintProperty(MUNI_OUTLINE, "line-opacity", outlineOpacity);
    } else {
      map.setLayoutProperty(MUNI_OUTLINE, "visibility", "none");
    }
  }

  if (isFLIRMode) {
    const style = map.getStyle();
    if (style && style.layers) {
      style.layers.forEach((layer) => {
        if (
          layer.id.includes("label") ||
          layer.id.includes("road") ||
          layer.id.includes("building") ||
          layer.id.includes("place") ||
          layer.id.includes("poi") ||
          layer.id.includes("transit") ||
          layer.id.includes("water-label") ||
          layer.id.includes("land-structure")
        ) {
          if (map.getLayer(layer.id)) {
            map.setLayoutProperty(layer.id, "visibility", "none");
          }
        }
      });
    }
    if (map.getPaintProperty("background", "background-color")) {
      map.setPaintProperty("background", "background-color", "#000000");
    }
  } else {
    const style = map.getStyle();
    if (style && style.layers) {
      style.layers.forEach((layer) => {
        if (
          layer.id.includes("label") ||
          layer.id.includes("road") ||
          layer.id.includes("building") ||
          layer.id.includes("place") ||
          layer.id.includes("poi") ||
          layer.id.includes("transit") ||
          layer.id.includes("water-label") ||
          layer.id.includes("land-structure")
        ) {
          if (map.getLayer(layer.id)) {
            map.setLayoutProperty(layer.id, "visibility", "visible");
          }
        }
      });
    }
    if (map.getPaintProperty("background", "background-color")) {
      map.setPaintProperty("background", "background-color", "#0b0f14");
    }
  }

}

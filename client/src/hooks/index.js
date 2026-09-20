import { useState, useEffect, useRef, useCallback } from "react";
import { formatUTCTime, buildMunicipalitiesGeoJSON, buildWaterBodiesGeoJSON } from "../utils/helpers";
import { CITY_CONFIG } from "../constants/cities";
import { MAPBOX_TOKEN } from "../constants/layers";
import { getApiUrl } from "../utils/api";
import mapboxgl from "mapbox-gl";

// ═══════════════════════════════════════════════════════════════════════════
// DIAGNOSTIC STARTUP CONFIRMATION
// ═══════════════════════════════════════════════════════════════════════════
console.log("═".repeat(80));
console.log("[GEOSENSE DIAGNOSTICS ACTIVE] - hooks/index.js loaded");
console.log("Timestamp:", new Date().toISOString());
console.log("MAPBOX_TOKEN available:", !!MAPBOX_TOKEN);
console.log("═".repeat(80));
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
const WATER_SOURCE = "water-bodies";
const WATER_FILL = "water-fill";
const WATER_OUTLINE = "water-outline";
const AQI_SURFACE_SOURCE = "aqi-surface";
const AQI_SURFACE_LAYER = "aqi-surface-raster";
const NDVI_SURFACE_SOURCE = "ndvi-surface";
const NDVI_SURFACE_LAYER = "ndvi-surface-raster";
const LST_GLOW_SOURCE = "lst-glow";
const LST_GLOW_LAYER = "lst-glow-raster";
const LST_SURFACE_SOURCE = "lst-surface";
const LST_SURFACE_LAYER = "lst-surface-raster";

function getMetricProp(layerId) {
  switch (layerId) {
    case "aqi": return "aqi_norm";
    case "ndvi": return "ndvi_norm";
    case "lst": return "lst_norm";
    case "water_health": return "water_norm";
    case "all": return "composite_norm";
    default: return "composite_norm";
  }
}

function buildFillColorExpression(layerId) {
  const prop = getMetricProp(layerId);
  const ramps = {
    aqi_norm: [[0.0, "#1dd1a1"], [0.28, "#ffd32a"], [0.45, "#ff8c00"], [0.69, "#ff3b3b"], [0.84, "#8F3F97"], [1.0, "#7E0023"]],
    ndvi_norm: [[0.0, "#006400"], [0.2, "#32CD32"], [0.4, "#FFFF00"], [0.6, "#D2B48C"], [0.8, "#8B4513"], [1.0, "#5C4033"]],
    lst_norm: [[0.0, "#00BFFF"], [0.25, "#1dd1a1"], [0.45, "#ffd32a"], [0.65, "#ff8c00"], [0.85, "#ff3b3b"], [1.0, "#8B0000"]],
    composite_norm: [[0.0, "#1dd1a1"], [0.25, "#ffd32a"], [0.50, "#ff8c00"], [0.70, "#ff3b3b"], [0.85, "#8F3F97"], [1.0, "#7E0023"]],
  };
  const stops = ramps[prop] || ramps["composite_norm"];
  return [
    "case",
    ["==", ["get", prop], null],
    "#1a1a2e",
    ["interpolate", ["linear"], ["get", prop], ...stops.flatMap(([s, c]) => [s, c])],
  ];
}

function getPrimaryLayerId(activeLayers) {
  if (!activeLayers) return "all";
  if (activeLayers.all) return "all";
  return Object.entries(activeLayers).find(([, v]) => v)?.[0] || "all";
}

function shouldSkipFlyTo(map, targetCenter, targetZoom) {
  if (!map || !Array.isArray(targetCenter) || targetCenter.length < 2 || typeof targetZoom !== "number") return false;
  try {
    const c = map.getCenter();
    return Math.abs(c.lng - targetCenter[0]) < CENTER_EPSILON &&
      Math.abs(c.lat - targetCenter[1]) < CENTER_EPSILON &&
      Math.abs(map.getZoom() - targetZoom) < ZOOM_EPSILON;
  } catch (_) { return false; }
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
  const show = useCallback((msg) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setMessage(msg);
    setPhase("in");
    timerRef.current = setTimeout(() => {
      setPhase("out");
      setTimeout(() => setMessage(null), 350);
    }, duration);
  }, [duration]);
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);
  return { message, phase, show };
}

export function useIntro() {
  const [phase, setPhase] = useState("in");
  const [panelsVisible, setPanelsVisible] = useState(false);
  useEffect(() => {
    const t1 = setTimeout(() => setPhase("out"), 2200);
    const t2 = setTimeout(() => { setPhase("done"); setPanelsVisible(true); }, 3100);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);
  return { phase, panelsVisible };
}

export function useMapbox({ containerRef, activeCity, activeLayers, onZoneClick, liveMunicipalities = [], waterBodies = [], aqiSurface = null, ndviSurface = null, lstSurface = null, boundary = null }) {
  // ═══════════════════════════════════════════════════════════════════════════
  // DIAGNOSTIC: Hook execution confirmation
  // ═══════════════════════════════════════════════════════════════════════════
  console.log("🚨🚨🚨 [CACHE BUSTER v2.0 - Sep 20 2026 08:50] 🚨🚨🚨");
  console.log("[GEOSENSE DIAGNOSTICS] useMapbox hook called");
  console.log("  activeCity:", activeCity);
  console.log("  activeLayers:", activeLayers);
  console.log("  aqiSurface:", !!aqiSurface);
  console.log("  ndviSurface:", !!ndviSurface);
  console.log("  lstSurface:", !!lstSurface);
  console.log("  lstSurface actual value:", lstSurface);
  console.log("🚨🚨🚨 END CACHE BUSTER 🚨🚨🚨");
  // ═══════════════════════════════════════════════════════════════════════════

  const mapRef = useRef(null);
  const onZoneClickRef = useRef(onZoneClick);
  const pendingCityRef = useRef(null);
  const activeLayersRef = useRef(activeLayers);
  const liveMunisRef = useRef(liveMunicipalities);
  const waterBodiesRef = useRef(waterBodies);
  const selectedMuniRef = useRef(null);
  const aqiSurfaceRef = useRef(aqiSurface);
  const ndviSurfaceRef = useRef(ndviSurface);
  const lstSurfaceRef = useRef(lstSurface);

  useEffect(() => { onZoneClickRef.current = onZoneClick; }, [onZoneClick]);
  useEffect(() => { activeLayersRef.current = activeLayers; }, [activeLayers]);

  useEffect(() => {
    liveMunisRef.current = liveMunicipalities;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const sync = () => {
      const src = map.getSource(MUNI_SOURCE);
      if (src) src.setData(buildMunicipalitiesGeoJSON(liveMunisRef.current));
      applyMunicipalityPaint(map, activeLayersRef.current, selectedMuniRef.current, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
    };
    if (map.isStyleLoaded()) sync(); else map.once("idle", sync);
  }, [liveMunicipalities]);

  useEffect(() => {
    waterBodiesRef.current = waterBodies;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const sync = () => {
      const src = map.getSource(WATER_SOURCE);
      if (src) src.setData(buildWaterBodiesGeoJSON(waterBodiesRef.current));
    };
    if (map.isStyleLoaded()) sync(); else map.once("idle", sync);
  }, [waterBodies]);

  useEffect(() => {
    aqiSurfaceRef.current = aqiSurface;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !aqiSurface) return;
    const imageOptions = {
      url: getApiUrl(aqiSurface.image_url),
      coordinates: aqiSurface.coordinates,
    };
    const sync = () => {
      const source = map.getSource(AQI_SURFACE_SOURCE);
      if (source) source.updateImage(imageOptions);
      else map.addSource(AQI_SURFACE_SOURCE, { type: "image", ...imageOptions });
      if (!map.getLayer(AQI_SURFACE_LAYER)) {
        map.addLayer({
          id: AQI_SURFACE_LAYER, type: "raster", source: AQI_SURFACE_SOURCE,
          layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
        },
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined);
      }
      applyMunicipalityPaint(map, activeLayersRef.current, selectedMuniRef.current, true, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
    };
    if (map.isStyleLoaded()) sync(); else map.once("idle", sync);
  }, [aqiSurface]);

  useEffect(() => {
    ndviSurfaceRef.current = ndviSurface;
    const map = mapRef.current;

    // Need both map and data. Style structure readiness is checked inside syncNDVI.
    if (!map || !ndviSurface) return;

    function syncNDVI() {
      // Called only after style is confirmed ready (style.load has fired).
      const imageOptions = {
        url: getApiUrl(ndviSurface.image_url),
        coordinates: ndviSurface.coordinates,
      };

      // Source — create once, update if already exists
      const existingSource = map.getSource(NDVI_SURFACE_SOURCE);
      if (existingSource) {
        existingSource.updateImage(imageOptions);
      } else {
        map.addSource(NDVI_SURFACE_SOURCE, { type: "image", ...imageOptions });
      }

      // Layer — create once, idempotent
      if (!map.getLayer(NDVI_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: NDVI_SURFACE_LAYER,
            type: "raster",
            source: NDVI_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": 0.82,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          // Insert below municipality extrusion so municipalities stay on top.
          // If MUNI_EXTRUDE hasn't been added yet, insert at top of stack.
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined
        );
      }

      // Sync visibility to current layer state
      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        true
      );
    }

    // Probe whether style.load has already fired: in Mapbox GL JS v3,
    // map.getStyle() throws "Style is not done loading" before style.load.
    // After style.load it succeeds. We use this as the readiness signal.
    let styleReady = false;
    try { map.getStyle(); styleReady = true; } catch (_) { styleReady = false; }

    if (styleReady) {
      // style.load already fired — run immediately
      syncNDVI();
    } else {
      // style.load hasn't fired yet — register once listener
      const onStyleLoad = () => syncNDVI();
      map.once("style.load", onStyleLoad);
      return () => map.off("style.load", onStyleLoad);
    }
  }, [ndviSurface]);

  useEffect(() => {
    lstSurfaceRef.current = lstSurface;
    const map = mapRef.current;

    // Need both map and data. Style structure readiness is checked inside syncLST.
    if (!map || !lstSurface) return;

    function syncLST() {
      // Called only after style is confirmed ready (style.load has fired).

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
              "raster-opacity": 0.50,  // Stronger glow for FLIR effect
              "raster-fade-duration": 400,
              "raster-resampling": "linear",
            },
          },
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined
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
        map.addSource(LST_SURFACE_SOURCE, { type: "image", ...sharpImageOptions });
      }
      if (!map.getLayer(LST_SURFACE_LAYER)) {
        map.addLayer(
          {
            id: LST_SURFACE_LAYER,
            type: "raster",
            source: LST_SURFACE_SOURCE,
            layout: { visibility: "none" },
            paint: {
              "raster-opacity": 0.95,  // Very bright for FLIR hot-object glow
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
          },
          map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined
        );
      }

      // Sync visibility to current layer state
      applyMunicipalityPaint(
        map,
        activeLayersRef.current,
        selectedMuniRef.current,
        !!aqiSurfaceRef.current,
        !!ndviSurfaceRef.current,
        true
      );
    }

    // Probe whether style.load has already fired
    let styleReady = false;
    try { map.getStyle(); styleReady = true; } catch (_) { styleReady = false; }

    if (styleReady) {
      syncLST();
    } else {
      const onStyleLoad = () => syncLST();
      map.once("style.load", onStyleLoad);
      return () => map.off("style.load", onStyleLoad);
    }
  }, [lstSurface]);

  useEffect(() => {
    // ═══════════════════════════════════════════════════════════════════════════
    // DIAGNOSTIC: Map initialization useEffect triggered
    // ═══════════════════════════════════════════════════════════════════════════
    console.log("[GEOSENSE DIAGNOSTICS] Map initialization useEffect triggered");
    console.log("  containerRef.current exists:", !!containerRef.current);
    console.log("  mapRef.current exists:", !!mapRef.current);
    console.log("🚨 [MAP DIAGNOSTIC VERSION] guard check: containerRef.current =", !!containerRef.current, "| mapRef.current =", !!mapRef.current);
    // ═══════════════════════════════════════════════════════════════════════════

    if (!containerRef.current || mapRef.current) return;
    const token = MAPBOX_TOKEN;

    // ═══════════════════════════════════════════════════════════════════════════
    // MAPBOX TOKEN DIAGNOSTIC
    // ═══════════════════════════════════════════════════════════════════════════
    console.group("🗺️ MAPBOX CONFIGURATION");
    console.log("Token exists:", !!token);
    console.log("Token starts with 'pk.':", token?.startsWith('pk.'));
    console.log("Token length:", token?.length);
    console.log("Token first 20 chars:", token?.substring(0, 20));
    console.log("Map style:", MAP_STYLE);
    console.groupEnd();
    // ═══════════════════════════════════════════════════════════════════════════

    if (!token || token === "YOUR_MAPBOX_TOKEN_HERE") return;
    mapboxgl.accessToken = token;

    console.log("🚨 [MAP DIAGNOSTIC VERSION] lifecycle instrumentation build ALPHA-1");

    const map = new mapboxgl.Map({
      container: containerRef.current, style: MAP_STYLE,
      center: INDIA_CENTER, zoom: INDIA_ZOOM,
      pitch: 0, bearing: 0, projection: "mercator",
      antialias: true, attributionControl: false, logoPosition: "bottom-right",
    });

    console.log("🚨 [MAP DIAGNOSTIC VERSION] map constructor completed ALPHA-1");
    mapRef.current = map;

    // ═══════════════════════════════════════════════════════════════════════════
    // [MAP LIFECYCLE] Map instance identity + lifecycle event diagnostics
    // ═══════════════════════════════════════════════════════════════════════════
    const mapInstanceId = "map-" + Date.now();
    map._diagnosticId = mapInstanceId;
    console.group("🏗️ [MAP LIFECYCLE] new mapboxgl.Map() created");
    console.log("  mapInstanceId:", mapInstanceId);
    console.log("  Timestamp:", new Date().toISOString());
    console.log("  map.isStyleLoaded() at creation:", map.isStyleLoaded());
    console.log("  map.getStyle() at creation: (not called — throws in v3 before style.load)");
    console.groupEnd();

    map.on("styledata", () => {
      console.log("📋 [MAP LIFECYCLE] 'styledata' event");
      console.log("  mapInstanceId:", map._diagnosticId);
      console.log("  Timestamp:", new Date().toISOString());
      console.log("  map.isStyleLoaded():", map.isStyleLoaded());
      console.log("  map.getStyle() exists:", !!map.getStyle());
    });

    map.on("style.load", () => {
      console.group("🎨 [MAP LIFECYCLE] 'style.load' event fired");
      console.log("  mapInstanceId:", map._diagnosticId);
      console.log("  Timestamp:", new Date().toISOString());
      console.log("  map.isStyleLoaded():", map.isStyleLoaded());
      console.log("  map.getStyle() exists:", !!map.getStyle());
      console.groupEnd();
    });

    map.on("load", () => {
      console.group("✅ [MAP LIFECYCLE] 'load' event fired");
      console.log("  mapInstanceId:", map._diagnosticId);
      console.log("  Timestamp:", new Date().toISOString());
      console.log("  map.isStyleLoaded():", map.isStyleLoaded());
      console.log("  map.getStyle() exists:", !!map.getStyle());
      console.groupEnd();
    });

    map.on("idle", () => {
      console.log("💤 [MAP LIFECYCLE] 'idle' event fired");
      console.log("  mapInstanceId:", map._diagnosticId);
      console.log("  Timestamp:", new Date().toISOString());
      console.log("  map.isStyleLoaded():", map.isStyleLoaded());
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
      const isNdviRelated = e.sourceId === NDVI_SURFACE_SOURCE ||
        (e.error?.message && e.error.message.includes('ndvi')) ||
        (e.error?.url && e.error.url.includes('ndvi'));

      if (isNdviRelated) {
        console.group("🔴 [MAPBOX ERROR] NDVI-RELATED ERROR DETECTED");
        console.error("  Timestamp:", new Date().toISOString());
        console.error("  Error count:", mapboxErrorCount);
        console.error("  sourceId:", e.sourceId);
        console.error("  error.message:", e.error?.message);
        console.error("  error.url:", e.error?.url);
        console.error("  Full error object:", e.error);
        console.error("  Full event:", e);
        console.groupEnd();
      }
      // ═══════════════════════════════════════════════════════════════════════════

      // Extract URL
      const errorMsg = e.error?.message || e.error?.toString() || '';
      const urlMatch = errorMsg.match(/https?:\/\/[^\s]+/);
      const failedUrl = urlMatch ? urlMatch[0] : 'unknown';

      // Only log detailed info for first few errors and unique URLs (unless NDVI-related, always log those)
      const shouldLogDetailed = isNdviRelated || mapboxErrorCount <= 5 || !errorUrlsSeen.has(failedUrl);

      if (shouldLogDetailed) {
        console.group(`❌ Mapbox Error #${mapboxErrorCount}${isNdviRelated ? ' [NDVI]' : ''}`);
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
          if (urlMatch[0].includes('/v4/')) {
            console.error("    Resource type: Mapbox Vector Tile (v4 API - LEGACY)");
            console.error("    ⚠️ WARNING: v4 API is deprecated. Modern Mapbox uses vector tiles v2.");
          } else if (urlMatch[0].includes('/sprites/')) {
            console.error("    Resource type: Sprite");
          } else if (urlMatch[0].includes('/fonts/') || urlMatch[0].includes('/glyphs/')) {
            console.error("    Resource type: Font/Glyph");
          } else if (urlMatch[0].includes('/styles/')) {
            console.error("    Resource type: Style");
          } else if (urlMatch[0].includes('/surface-assets/') || urlMatch[0].includes('ndvi')) {
            console.error("    Resource type: NDVI Surface Asset");
          }
        }

        console.error("    Timestamp:", new Date().toISOString());
        console.groupEnd();
      }

      // Summary every 25 errors
      if (mapboxErrorCount % 25 === 0) {
        console.warn(`📊 Mapbox Error Summary: ${mapboxErrorCount} total errors`);
        console.warn(`    Unique URLs failing: ${errorUrlsSeen.size}`);
        console.warn(`    URLs:`, Array.from(errorUrlsSeen));
      }
    });

    map.on("data", (e) => {
      if (e.sourceId === NDVI_SURFACE_SOURCE && e.isSourceLoaded) {
        console.group("✅ [NDVI DATA EVENT] NDVI source data loaded successfully");
        console.log("  Timestamp:", new Date().toISOString());
        console.log("  sourceId:", e.sourceId);
        console.log("  isSourceLoaded:", e.isSourceLoaded);
        console.log("  dataType:", e.dataType);
        console.groupEnd();
      }
    });

    map.on("sourcedata", (e) => {
      if (e.sourceId === NDVI_SURFACE_SOURCE) {
        console.group("📡 [NDVI SOURCEDATA EVENT]");
        console.log("  Timestamp:", new Date().toISOString());
        console.log("  isSourceLoaded:", e.isSourceLoaded);
        console.log("  dataType:", e.dataType);
        console.log("  tile:", e.tile);
        console.log("  coord:", e.coord);
        console.groupEnd();
      }
    });
    // ═══════════════════════════════════════════════════════════════════════════

    const handleMuniClick = (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      let zone = null;
      try { zone = JSON.parse(feature.properties.zone_json); } catch (_) { return; }
      if (!zone) return;
      const muniId = feature.properties.id;
      selectedMuniRef.current = muniId;
      applyMunicipalityPaint(map, activeLayersRef.current, muniId, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
      onZoneClickRef.current?.(zone);
      map.stop();
      map.easeTo({ center: [e.lngLat.lng, e.lngLat.lat], zoom: Math.max(map.getZoom(), 10.5), pitch: 52, bearing: -10, duration: 1100, essential: true });
    };

    let hoveredId = null;
    const handleMouseMove = (e) => {
      if (e.features.length > 0) {
        if (hoveredId !== null) map.setFeatureState({ source: MUNI_SOURCE, id: hoveredId }, { hovered: false });
        hoveredId = e.features[0].id;
        map.setFeatureState({ source: MUNI_SOURCE, id: hoveredId }, { hovered: true });
      }
    };
    const handleMouseLeave = () => {
      if (hoveredId !== null) { map.setFeatureState({ source: MUNI_SOURCE, id: hoveredId }, { hovered: false }); hoveredId = null; }
      map.getCanvas().style.cursor = "";
    };
    const handleMouseEnter = () => { map.getCanvas().style.cursor = "crosshair"; };

    const setupLayers = () => {
      // ═══════════════════════════════════════════════════════════════════════════
      // [MAP LIFECYCLE] setupLayers() entry
      // ═══════════════════════════════════════════════════════════════════════════
      console.group("🔧 [MAP LIFECYCLE] setupLayers() called");
      console.log("  mapInstanceId:", map._diagnosticId);
      console.log("  Timestamp:", new Date().toISOString());
      console.log("  map.isStyleLoaded() BEFORE:", map.isStyleLoaded());
      console.log("  map.getStyle() exists:", !!map.getStyle());
      // ═══════════════════════════════════════════════════════════════════════════

      const style = map.getStyle();
      if (style?.layers) {
        style.layers.forEach((layer) => {
          const iconImage = layer.layout?.["icon-image"];
          if (iconImage && JSON.stringify(iconImage).includes("in-state")) {
            try { map.setLayoutProperty(layer.id, "icon-image", undefined); } catch (_) { }
          }
        });
      }

      if (!map.getSource(MUNI_SOURCE)) map.addSource(MUNI_SOURCE, { type: "geojson", data: buildMunicipalitiesGeoJSON(liveMunisRef.current), promoteId: "id" });
      if (!map.getSource(WATER_SOURCE)) map.addSource(WATER_SOURCE, { type: "geojson", data: buildWaterBodiesGeoJSON(waterBodiesRef.current), promoteId: "id" });

      // Create MUNI_EXTRUDE layer FIRST so raster layers can reference it with beforeId
      if (!map.getLayer(MUNI_EXTRUDE)) {
        map.addLayer({
          id: MUNI_EXTRUDE, type: "fill-extrusion", source: MUNI_SOURCE,
          paint: { "fill-extrusion-color": "#2a2a3a", "fill-extrusion-height": 0, "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.85 }
        });
      }

      // Now add AQI raster layer positioned before MUNI_EXTRUDE.
      // NDVI source/layer are owned exclusively by the ndviSurface useEffect (syncNDVI).
      if (aqiSurfaceRef.current && !map.getSource(AQI_SURFACE_SOURCE)) {
        map.addSource(AQI_SURFACE_SOURCE, { type: "image", url: getApiUrl(aqiSurfaceRef.current.image_url), coordinates: aqiSurfaceRef.current.coordinates });
      }
      if (map.getSource(AQI_SURFACE_SOURCE) && !map.getLayer(AQI_SURFACE_LAYER)) {
        map.addLayer({
          id: AQI_SURFACE_LAYER, type: "raster", source: AQI_SURFACE_SOURCE,
          layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
        }, MUNI_EXTRUDE);
      }
      if (!map.getLayer(MUNI_OUTLINE)) {
        map.addLayer({
          id: MUNI_OUTLINE, type: "line", source: MUNI_SOURCE,
          // Start all boundaries very subdued — applyMunicipalityPaint raises
          // the selected boundary on click.
          paint: { "line-color": "#00e5ff", "line-width": 0.5, "line-opacity": 0.18 }
        });
      }
      // No MUNI_LABEL layer: the Mapbox dark-v11 basemap already supplies
      // place/city labels for Mumbai and its districts.  Adding a GeoSense
      // symbol layer on top produces duplicate labels at every municipality.
      if (!map.getLayer(WATER_FILL)) {
        map.addLayer({
          id: WATER_FILL, type: "fill", source: WATER_SOURCE, layout: { visibility: "none" },
          paint: { "fill-color": "#0fb8c9", "fill-opacity": 0.82 }
        });
      }
      if (!map.getLayer(WATER_OUTLINE)) {
        map.addLayer({
          id: WATER_OUTLINE, type: "line", source: WATER_SOURCE, layout: { visibility: "none" },
          paint: { "line-color": "#00e5ff", "line-width": 1.2, "line-opacity": 0.65 }
        });
      }

      map.off("click", MUNI_EXTRUDE, handleMuniClick); map.off("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.off("mouseleave", MUNI_EXTRUDE, handleMouseLeave); map.off("mousemove", MUNI_EXTRUDE, handleMouseMove);
      map.on("click", MUNI_EXTRUDE, handleMuniClick); map.on("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.on("mouseleave", MUNI_EXTRUDE, handleMouseLeave); map.on("mousemove", MUNI_EXTRUDE, handleMouseMove);

      applyMunicipalityPaint(map, activeLayersRef.current, selectedMuniRef.current, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
      if (pendingCityRef.current) { const p = pendingCityRef.current; pendingCityRef.current = null; flyToCity(map, p); }

      // ═══════════════════════════════════════════════════════════════════════════
      // [MAP LIFECYCLE] setupLayers() exit
      // ═══════════════════════════════════════════════════════════════════════════
      console.log("  map.isStyleLoaded() AFTER setupLayers:", map.isStyleLoaded());
      console.log("  map.getStyle() exists AFTER:", !!map.getStyle());
      console.log("  ndviSurfaceRef.current at setupLayers time:", !!ndviSurfaceRef.current);
      console.groupEnd();
      // ═══════════════════════════════════════════════════════════════════════════
    };

    map.on("style.load", setupLayers);
    return () => {
      map.off("style.load", setupLayers);
      map.off("click", MUNI_EXTRUDE, handleMuniClick); map.off("mouseenter", MUNI_EXTRUDE, handleMouseEnter);
      map.off("mouseleave", MUNI_EXTRUDE, handleMouseLeave); map.off("mousemove", MUNI_EXTRUDE, handleMouseMove);

      // ═══════════════════════════════════════════════════════════════════════════
      // TEMPORARY CLEANUP DIAGNOSTIC
      // ═══════════════════════════════════════════════════════════════════════════
      console.log("12. React cleanup - checking for layer/source removal");
      console.log("    NDVI layer exists before cleanup:", !!map.getLayer(NDVI_SURFACE_LAYER));
      console.log("    NDVI source exists before cleanup:", !!map.getSource(NDVI_SURFACE_SOURCE));
      // ═══════════════════════════════════════════════════════════════════════════

      map.remove(); mapRef.current = null;
    };
  }, [containerRef]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!activeCity) {
      const map = mapRef.current;
      if (map) map.easeTo({ center: INDIA_CENTER, zoom: INDIA_ZOOM, pitch: 0, bearing: 0, duration: 1400, essential: true });
      return;
    }
    const city = CITY_CONFIG[activeCity];
    if (!city) return;
    const map = mapRef.current;
    if (map && map.isStyleLoaded()) {
      flyToCity(map, city);
    } else {
      pendingCityRef.current = city;
      let attempts = 0;
      const timer = setInterval(() => {
        attempts++;
        const m = mapRef.current;
        if (m && m.isStyleLoaded()) { clearInterval(timer); pendingCityRef.current = null; flyToCity(m, city); }
        else if (attempts > 20) clearInterval(timer);
      }, 200);
      return () => clearInterval(timer);
    }
  }, [activeCity]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyMunicipalityPaint(map, activeLayers, selectedMuniRef.current, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current);
  }, [activeLayers]);

  return mapRef;
}

function flyToCity(map, city) {
  const targetZoom = city.zoom ?? 10.5;
  if (shouldSkipFlyTo(map, city.center, targetZoom)) return;
  map.stop();
  map.flyTo({ center: city.center, zoom: targetZoom, pitch: 50, bearing: -10, duration: 2600, essential: true, curve: 1.6, speed: 0.65 });
}

function applyMunicipalityPaint(map, activeLayers, selectedMuniId, hasAqiSurface = false, hasNdviSurface = false, hasLstSurface = false) {
  if (!map || !map.isStyleLoaded()) return;
  const layerId = getPrimaryLayerId(activeLayers);
  const isWaterMode = layerId === "water_health";
  const isAqiSurfaceMode = layerId === "aqi" && hasAqiSurface;
  const isNdviSurfaceMode = layerId === "ndvi" && hasNdviSurface;
  const isLstSurfaceMode = layerId === "lst" && hasLstSurface;
  const isSurfaceMode = isAqiSurfaceMode || isNdviSurfaceMode || isLstSurfaceMode;

  // FLIR mode: LST active = pitch black map, only thermal glow visible
  // Municipality polygons destroy the FLIR aesthetic — hide them completely
  const isFLIRMode = isLstSurfaceMode;

  console.log("🔍 [SURFACE MODE DETECTION]");
  console.log("  layerId:", layerId);
  console.log("  hasLstSurface:", hasLstSurface);
  console.log("  isLstSurfaceMode:", isLstSurfaceMode);
  console.log("  isNdviSurfaceMode:", isNdviSurfaceMode);
  console.log("  isFLIRMode:", isFLIRMode);

  // ═══════════════════════════════════════════════════════════════════════════
  // TEMPORARY NDVI DIAGNOSTIC LOGGING
  // ═══════════════════════════════════════════════════════════════════════════
  if (layerId === "ndvi" || isNdviSurfaceMode) {
    console.group("🔍 NDVI RUNTIME DIAGNOSTIC");
    console.log("1. activeLayers:", JSON.stringify(activeLayers, null, 2));
    console.log("2. getPrimaryLayerId(activeLayers):", layerId);
    console.log("3. hasNdviSurface:", hasNdviSurface);
    console.log("4. isNdviSurfaceMode:", isNdviSurfaceMode);

    const ndviSource = map.getSource(NDVI_SURFACE_SOURCE);
    const ndviLayer = map.getLayer(NDVI_SURFACE_LAYER);
    console.log("5. map.getSource(NDVI_SURFACE_SOURCE) exists:", !!ndviSource);
    if (ndviSource) {
      console.log("   Source type:", ndviSource.type);
      try {
        const sourceData = map.getSource(NDVI_SURFACE_SOURCE).serialize();
        console.log("   Source URL:", sourceData.url);
        console.log("   Source coordinates:", sourceData.coordinates);
      } catch (e) {
        console.log("   Could not serialize source:", e.message);
      }
    }

    console.log("6. map.getLayer(NDVI_SURFACE_LAYER) exists:", !!ndviLayer);
    if (ndviLayer) {
      console.log("   Layer type:", ndviLayer.type);
      console.log("   Layer source:", ndviLayer.source);
      try {
        const visibility = map.getLayoutProperty(NDVI_SURFACE_LAYER, "visibility");
        const opacity = map.getPaintProperty(NDVI_SURFACE_LAYER, "raster-opacity");
        console.log("7. NDVI layer visibility:", visibility);
        console.log("8. NDVI raster opacity:", opacity);
      } catch (e) {
        console.log("   Could not get layer properties:", e.message);
      }
    }

    // List all layers to see ordering
    const allLayers = map.getStyle().layers.map(l => l.id);
    const ndviIndex = allLayers.indexOf(NDVI_SURFACE_LAYER);
    const muniIndex = allLayers.indexOf(MUNI_EXTRUDE);
    console.log("   Layer stack positions:");
    console.log("   - NDVI_SURFACE_LAYER at index:", ndviIndex);
    console.log("   - MUNI_EXTRUDE at index:", muniIndex);
    console.log("   - Layer order (NDVI before MUNI?):", ndviIndex !== -1 && muniIndex !== -1 && ndviIndex < muniIndex);

    console.groupEnd();
  }
  // ═══════════════════════════════════════════════════════════════════════════

  if (map.getLayer(AQI_SURFACE_LAYER)) {
    map.setLayoutProperty(AQI_SURFACE_LAYER, "visibility", isAqiSurfaceMode ? "visible" : "none");
  }
  if (map.getLayer(NDVI_SURFACE_LAYER)) {
    map.setLayoutProperty(NDVI_SURFACE_LAYER, "visibility", isNdviSurfaceMode ? "visible" : "none");
  }
  if (map.getLayer(LST_GLOW_LAYER)) {
    map.setLayoutProperty(LST_GLOW_LAYER, "visibility", isLstSurfaceMode ? "visible" : "none");
  }
  if (map.getLayer(LST_SURFACE_LAYER)) {
    map.setLayoutProperty(LST_SURFACE_LAYER, "visibility", isLstSurfaceMode ? "visible" : "none");
  }

  if (map.getLayer(MUNI_EXTRUDE)) {
    // FLIR mode: hide municipality fills completely — only thermal surface should be visible
    if (isFLIRMode) {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "none");
    } else {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "visible");
      // In AQI-surface mode municipal polygons are context/selection only.  They
      // must never overlay a municipality-wide AQI colour on the raster.
      const colorExpr = (isWaterMode || isSurfaceMode) ? "#0e0e1a" : buildFillColorExpression(layerId);
      // fill-extrusion-opacity does NOT support data/feature expressions in Mapbox GL JS v3.
      // Use a constant per mode. Selection emphasis is conveyed via height and outline instead.
      const opacityExpr = isSurfaceMode ? 0.08
        : isWaterMode ? 0.12
          : 0.82;
      const heightExpr = (selectedMuniId != null && !isWaterMode)
        ? ["case", ["==", ["get", "id"], selectedMuniId], SELECTED_MUNI_HEIGHT, 0]
        : 0;
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-color", colorExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-opacity", opacityExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-height", heightExpr);
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-base", 0);
    }
  }

  if (map.getLayer(MUNI_OUTLINE)) {
    // FLIR mode: hide outlines — only thermal glow
    if (isFLIRMode) {
      map.setLayoutProperty(MUNI_OUTLINE, "visibility", "none");
    } else {
      map.setLayoutProperty(MUNI_OUTLINE, "visibility", "visible");
      const outlineColor = isWaterMode ? "#1e2a3a"
        : (selectedMuniId != null ? ["case", ["==", ["get", "id"], selectedMuniId], "#ffffff", "#00e5ff"] : "#00e5ff");
      const outlineWidth = selectedMuniId != null && !isWaterMode
        ? ["case", ["==", ["get", "id"], selectedMuniId], 2.2, 0.5]
        : 0.5;
      const outlineOpacity = isWaterMode ? 0.12
        : (selectedMuniId != null ? ["case", ["==", ["get", "id"], selectedMuniId], 0.85, 0.15] : 0.18);
      map.setPaintProperty(MUNI_OUTLINE, "line-color", outlineColor);
      map.setPaintProperty(MUNI_OUTLINE, "line-width", outlineWidth);
      map.setPaintProperty(MUNI_OUTLINE, "line-opacity", outlineOpacity);
    }
  }

  // FLIR mode: make basemap pitch black by hiding all basemap layers except the background
  if (isFLIRMode) {
    // Hide all label/road/building layers from the basemap
    const style = map.getStyle();
    if (style && style.layers) {
      style.layers.forEach(layer => {
        if (layer.id.includes('label') || layer.id.includes('road') ||
          layer.id.includes('building') || layer.id.includes('place') ||
          layer.id.includes('poi') || layer.id.includes('transit') ||
          layer.id.includes('water-label') || layer.id.includes('land-structure')) {
          if (map.getLayer(layer.id)) {
            map.setLayoutProperty(layer.id, 'visibility', 'none');
          }
        }
      });
    }
    // Make background pure black
    if (map.getPaintProperty('background', 'background-color')) {
      map.setPaintProperty('background', 'background-color', '#000000');
    }
  } else {
    // Restore basemap layers
    const style = map.getStyle();
    if (style && style.layers) {
      style.layers.forEach(layer => {
        if (layer.id.includes('label') || layer.id.includes('road') ||
          layer.id.includes('building') || layer.id.includes('place') ||
          layer.id.includes('poi') || layer.id.includes('transit') ||
          layer.id.includes('water-label') || layer.id.includes('land-structure')) {
          if (map.getLayer(layer.id)) {
            map.setLayoutProperty(layer.id, 'visibility', 'visible');
          }
        }
      });
    }
    // Restore original background
    if (map.getPaintProperty('background', 'background-color')) {
      map.setPaintProperty('background', 'background-color', '#0b0f14');
    }
  }

  // MUNI_LABEL was removed — basemap labels are used instead.

  const waterVis = isWaterMode ? "visible" : "none";
  if (map.getLayer(WATER_FILL)) {
    map.setLayoutProperty(WATER_FILL, "visibility", waterVis);
    if (isWaterMode) {
      const waterColorExpr = ["case", ["==", ["get", "water_norm"], null], "rgba(0,0,0,0)",
        ["interpolate", ["linear"], ["get", "water_norm"], 0.0, "#0fb8c9", 0.33, "#7ed321", 0.60, "#ff8c00", 1.0, "#ff3b3b"]];
      const waterOpacityExpr = ["case", ["==", ["get", "water_norm"], null], 0.0, 0.88];
      map.setPaintProperty(WATER_FILL, "fill-color", waterColorExpr);
      map.setPaintProperty(WATER_FILL, "fill-opacity", waterOpacityExpr);
    }
  }
  if (map.getLayer(WATER_OUTLINE)) map.setLayoutProperty(WATER_OUTLINE, "visibility", waterVis);
}

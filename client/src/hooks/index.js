import { useState, useEffect, useRef, useCallback } from "react";
import { formatUTCTime, buildGeoJSON } from "../utils/helpers";
import { CITY_CONFIG } from "../constants/cities";
import { LAYER_CONFIG, MAPBOX_TOKEN } from "../constants/layers";
import mapboxgl from "mapbox-gl";

const CENTER_EPSILON = 0.0005;
const ZOOM_EPSILON = 0.02;
const AUTO_ROTATE_INTERVAL_MS = 180;
const AUTO_ROTATE_STEP_DEG = 0.12;
const INDIA_CENTER = [79.0, 22.2];
const INDIA_ZOOM = 3.65;
const MAP_STYLE = "mapbox://styles/mapbox/satellite-streets-v12";

function getPrimaryLayerId(activeLayers) {
  if (!activeLayers) return "all";
  if (activeLayers.all) return "all";
  return Object.entries(activeLayers).find(([, value]) => value)?.[0] || "all";
}

function hasActiveLayers(activeLayers) {
  if (!activeLayers) return false;
  return Object.values(activeLayers).some((v) => v === true);
}

function updateLayerVisibility(map, activeLayers) {
  if (!map || !map.isStyleLoaded()) return;

  const isActive = hasActiveLayers(activeLayers);
  const visibility = isActive ? "visible" : "none";

  try {
    if (map.getLayer("env-heat")) {
      map.setLayoutProperty("env-heat", "visibility", visibility);
    }
    if (map.getLayer("env-circles")) {
      map.setLayoutProperty("env-circles", "visibility", visibility);
    }
  } catch (_) {
    // layer may not exist yet
  }
}

function buildHeatmapOpacityExpression(opacityPercent = 86) {
  const nearOpacity = Math.max(0, Math.min(1, opacityPercent / 100));
  const farOpacity = Math.max(0.2, nearOpacity * 0.5);
  return ["interpolate", ["linear"], ["zoom"], 7, nearOpacity, 16, farOpacity];
}

function applyHeatmapPaint(map, activeLayers) {
  if (!map || !map.isStyleLoaded() || !map.getLayer("env-heat")) return;

  const primaryLayer = getPrimaryLayerId(activeLayers);
  const gradient = LAYER_CONFIG[primaryLayer]?.gradient || LAYER_CONFIG.all.gradient;
  const colorExpr = [
    "interpolate", ["linear"], ["heatmap-density"],
    ...Object.entries(gradient).flatMap(([stop, color]) => [Number(stop), color]),
  ];

  map.setPaintProperty("env-heat", "heatmap-weight", ["interpolate", ["linear"], ["get", "severity"], 0, 0, 1, 1]);
  map.setPaintProperty("env-heat", "heatmap-color", colorExpr);
  map.setPaintProperty("env-heat", "heatmap-opacity", buildHeatmapOpacityExpression());
}

function shouldSkipFlyTo(map, targetCenter, targetZoom) {
  if (!map || !Array.isArray(targetCenter) || targetCenter.length < 2 || typeof targetZoom !== "number") {
    return false;
  }

  try {
    const currentCenter = map.getCenter();
    const currentZoom = map.getZoom();

    const lngDiff = Math.abs(currentCenter.lng - targetCenter[0]);
    const latDiff = Math.abs(currentCenter.lat - targetCenter[1]);
    const zoomDiff = Math.abs(currentZoom - targetZoom);

    return lngDiff < CENTER_EPSILON && latDiff < CENTER_EPSILON && zoomDiff < ZOOM_EPSILON;
  } catch (_) {
    return false;
  }
}

function flyToWithGuards(map, options) {
  const targetCenter = options?.center;
  const targetZoom = options?.zoom;
  if (shouldSkipFlyTo(map, targetCenter, targetZoom)) return false;
  map.stop();
  map.flyTo(options);
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// useClock
// Returns a live UTC timestamp string, updated every second
// ─────────────────────────────────────────────────────────────────────────────
export function useClock() {
  const [time, setTime] = useState(formatUTCTime());

  useEffect(() => {
    const id = setInterval(() => setTime(formatUTCTime()), 1000);
    return () => clearInterval(id);
  }, []);

  return time;
}

// ─────────────────────────────────────────────────────────────────────────────
// useToast
// Manages a timed notification toast
// Returns: { message, phase, show }
// ─────────────────────────────────────────────────────────────────────────────
export function useToast(duration = 1500) {
  const [message, setMessage] = useState(null);
  const [phase, setPhase] = useState("in"); // "in" | "out"
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

// ─────────────────────────────────────────────────────────────────────────────
// useIntro
// Manages the three-phase intro animation: "in" → "out" → "done"
// ─────────────────────────────────────────────────────────────────────────────
export function useIntro() {
  const [phase, setPhase] = useState("in");
  const [panelsVisible, setPanelsVisible] = useState(false);

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("out"), 2200);
    const t2 = setTimeout(() => {
      setPhase("done");
      setPanelsVisible(true);
    }, 3100);

    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  return { phase, panelsVisible };
}

// ─────────────────────────────────────────────────────────────────────────────
// useMapbox
// Initialises a Mapbox GL JS map instance and manages layers.
//
// PRODUCTION SETUP:
//   1. npm install mapbox-gl
//   2. import mapboxgl from 'mapbox-gl'
//   3. import 'mapbox-gl/dist/mapbox-gl.css'
//   4. Set VITE_MAPBOX_TOKEN in .env
//   5. Uncomment all mapboxgl code below
// ─────────────────────────────────────────────────────────────────────────────
export function useMapbox({ containerRef, activeCity, activeLayers, onZoneClick }) {
  const mapRef = useRef(null);
  const onZoneClickRef = useRef(onZoneClick);
  const pendingCityRef = useRef(null);   // stores city to fly to once map is ready
  const spinEnabledRef = useRef(false);  // disabled: map is locked to India overview
  const activeLayersRef = useRef(activeLayers);
  const activeCityRef = useRef(activeCity);

  useEffect(() => {
    onZoneClickRef.current = onZoneClick;
  }, [onZoneClick]);

  useEffect(() => {
    activeLayersRef.current = activeLayers;
  }, [activeLayers]);

  useEffect(() => {
    activeCityRef.current = activeCity;
  }, [activeCity]);

  // ── Initialize map ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const token = MAPBOX_TOKEN;
    if (!token || token === "YOUR_MAPBOX_TOKEN_HERE") return;

    mapboxgl.accessToken = token;

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

    mapRef.current = map;

    // ── Auto-rotation ──────────────────────────────────────────────────────
    function spinGlobe() {
      if (!spinEnabledRef.current || document.hidden) return;
      const zoom = map.getZoom();
      if (zoom < 5) {
        const bearing = map.getBearing();
        map.jumpTo({ bearing: bearing - AUTO_ROTATE_STEP_DEG });
      }
    }

    const spinTimer = setInterval(spinGlobe, AUTO_ROTATE_INTERVAL_MS);

    const stopSpinOnInteraction = () => {
      spinEnabledRef.current = false;
    };

    map.on("mousedown", stopSpinOnInteraction);
    map.on("touchstart", stopSpinOnInteraction);
    map.on("wheel", stopSpinOnInteraction);
    map.on("dragstart", stopSpinOnInteraction);
    map.on("zoomstart", stopSpinOnInteraction);
    map.on("rotatestart", stopSpinOnInteraction);
    map.on("pitchstart", stopSpinOnInteraction);

    const handleCircleClick = (event) => {
      const feature = event.features?.[0];
      if (!feature?.properties?.zone) return;

      const zone = JSON.parse(feature.properties.zone);

      onZoneClickRef.current?.(zone);

      const targetCenter = zone.coords;
      const targetZoom = 12.5;
      if (shouldSkipFlyTo(map, targetCenter, targetZoom)) return;

      flyToWithGuards(map, {
        center: targetCenter,
        zoom: targetZoom,
        duration: 900,
        essential: true,
      });
    };

    const handleMouseEnter = () => {
      map.getCanvas().style.cursor = "crosshair";
    };

    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = "crosshair";
    };

    const ensureEnvLayers = () => {
      const city = activeCityRef.current ? CITY_CONFIG[activeCityRef.current] : CITY_CONFIG.mumbai;

      map.setFog({
        "color": "rgb(100, 175, 240)",
        "high-color": "rgb(20,  80,  180)",
        "horizon-blend": 0.06,
        "space-color": "rgb(5,   5,   18)",
        "star-intensity": 0.90,
      });

      if (!map.getSource("env-anomalies")) {
        map.addSource("env-anomalies", {
          type: "geojson",
          data: buildGeoJSON(city),
        });
      } else {
        map.getSource("env-anomalies")?.setData(buildGeoJSON(city));
      }

      if (!map.getLayer("env-heat")) {
        map.addLayer({
          id: "env-heat",
          type: "heatmap",
          source: "env-anomalies",
          maxzoom: 18,
          layout: {
            "visibility": hasActiveLayers(activeLayersRef.current) ? "visible" : "none",
          },
          paint: {
            "heatmap-weight": ["interpolate", ["linear"], ["get", "severity"], 0, 0, 1, 1],
            "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 4, 0.7, 12, 2.4],
            "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 4, 26, 12, 72],
            "heatmap-opacity": buildHeatmapOpacityExpression(),
            "heatmap-color": [
              "interpolate", ["linear"], ["heatmap-density"],
              0, "rgba(0,0,0,0)",
              0.15, "rgba(29,209,161,0.6)",
              0.4, "rgba(255,211,42,0.75)",
              0.7, "rgba(255,140,0,0.85)",
              1, "rgba(255,59,59,0.95)",
            ],
          },
        });
      }

      if (!map.getLayer("env-circles")) {
        map.addLayer({
          id: "env-circles",
          type: "circle",
          source: "env-anomalies",
          minzoom: 8,
          layout: {
            "visibility": hasActiveLayers(activeLayersRef.current) ? "visible" : "none",
          },
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 18],
            "circle-color": ["get", "color"],
            "circle-opacity": 0.25,
            "circle-stroke-width": 1.3,
            "circle-stroke-color": ["get", "color"],
            "circle-stroke-opacity": 0.9,
            "circle-blur": 0.3,
          },
        });
      }

      map.off("click", "env-circles", handleCircleClick);
      map.off("mouseenter", "env-circles", handleMouseEnter);
      map.off("mouseleave", "env-circles", handleMouseLeave);

      map.on("click", "env-circles", handleCircleClick);
      map.on("mouseenter", "env-circles", handleMouseEnter);
      map.on("mouseleave", "env-circles", handleMouseLeave);

      applyHeatmapPaint(map, activeLayersRef.current);

      if (pendingCityRef.current) {
        const pendingCity = pendingCityRef.current;
        pendingCityRef.current = null;
        map.getSource("env-anomalies")?.setData(buildGeoJSON(pendingCity));
        const targetZoom = pendingCity.zoom ?? 11;
        flyToWithGuards(map, { center: pendingCity.center, zoom: targetZoom, duration: 2200, essential: true, curve: 1.8, speed: 0.7 });
      }
    };

    map.on("style.load", ensureEnvLayers);

    return () => {
      spinEnabledRef.current = false;
      clearInterval(spinTimer);
      map.off("mousedown", stopSpinOnInteraction);
      map.off("touchstart", stopSpinOnInteraction);
      map.off("wheel", stopSpinOnInteraction);
      map.off("dragstart", stopSpinOnInteraction);
      map.off("zoomstart", stopSpinOnInteraction);
      map.off("rotatestart", stopSpinOnInteraction);
      map.off("pitchstart", stopSpinOnInteraction);
      map.off("style.load", ensureEnvLayers);
      map.off("click", "env-circles", handleCircleClick);
      map.off("mouseenter", "env-circles", handleMouseEnter);
      map.off("mouseleave", "env-circles", handleMouseLeave);
      map.remove();
      mapRef.current = null;
    };
  }, [containerRef]); // ← do NOT include activeCity here — city changes are handled by the flyTo effect below

  // ── Fly to city whenever activeCity changes ────────────────────────────────
  useEffect(() => {
    if (!activeCity) {
      const map = mapRef.current;
      if (map && map.isStyleLoaded()) {
        flyToWithGuards(map, {
          center: INDIA_CENTER,
          zoom: INDIA_ZOOM,
          duration: 1400,
          essential: true,
          curve: 1.2,
          speed: 0.8,
        });
      }
      return;
    }

    const city = CITY_CONFIG[activeCity];
    if (!city) return;

    const doFly = (map) => {
      try {
        // Kill the globe spin FIRST — rotateTo cancels flyTo if it fires during animation
        spinEnabledRef.current = false;
        const source = map.getSource("env-anomalies");
        if (source) source.setData(buildGeoJSON(city));
        const targetZoom = city.zoom ?? 11;
        if (shouldSkipFlyTo(map, city.center, targetZoom)) return true;
        flyToWithGuards(map, { center: city.center, zoom: targetZoom, duration: 2200, essential: true, curve: 1.8, speed: 0.7 });
        return true;
      } catch (_) {
        return false;
      }
    };

    const map = mapRef.current;

    // Kill spin immediately regardless of map readiness
    spinEnabledRef.current = false;

    // Map ready right now — fly immediately
    if (map && map.isStyleLoaded()) {
      doFly(map);
      return;
    }

    // Map not ready yet — stash city so load handler picks it up
    pendingCityRef.current = city;

    // Also retry every 200 ms for up to 4 s in case load already fired
    let attempts = 0;
    const timer = setInterval(() => {
      attempts++;
      const m = mapRef.current;
      if (m && m.isStyleLoaded()) {
        clearInterval(timer);
        pendingCityRef.current = null;
        doFly(m);
      } else if (attempts > 20) {
        clearInterval(timer); // give up after 4 s
      }
    }, 200);

    return () => clearInterval(timer);
  }, [activeCity]);

  // ── Update heatmap gradient when active layers change ─────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyHeatmapPaint(map, activeLayers);
    updateLayerVisibility(map, activeLayers);
  }, [activeLayers]);

  return mapRef;
}

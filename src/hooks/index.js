import { useState, useEffect, useRef, useCallback } from "react";
import { formatUTCTime, buildGeoJSON } from "../utils/helpers";
import { CITY_CONFIG } from "../constants/cities";
import { LAYER_CONFIG, MAPBOX_TOKEN } from "../constants/layers";
import mapboxgl from "mapbox-gl";

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
export function useToast(duration = 2400) {
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
  const spinEnabledRef = useRef(true);   // shared flag — set false when a city is selected

  useEffect(() => {
    onZoneClickRef.current = onZoneClick;
  }, [onZoneClick]);

  // ── Initialize map ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const token = MAPBOX_TOKEN;
    if (!token || token === "YOUR_MAPBOX_TOKEN_HERE") return;

    mapboxgl.accessToken = token;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [78.9629, 20.5937],
      zoom: 2.0,
      pitch: 0,
      bearing: 0,
      projection: "globe",
      antialias: true,
      attributionControl: false,
      logoPosition: "bottom-right",
    });

    mapRef.current = map;

    // ── Auto-rotation ──────────────────────────────────────────────────────
    let userInteracting = false;

    function spinGlobe() {
      // Stop spinning as soon as user picks a city OR is dragging
      if (!spinEnabledRef.current || userInteracting) return;
      const zoom = map.getZoom();
      if (zoom < 5) {
        const bearing = map.getBearing();
        map.rotateTo(bearing - 0.15, { duration: 100, easing: t => t });
      }
    }

    const spinTimer = setInterval(spinGlobe, 100);

    map.on("mousedown", () => { userInteracting = true; });
    map.on("mouseup", () => { userInteracting = false; });
    map.on("touchstart", () => { userInteracting = true; });
    map.on("touchend", () => { userInteracting = false; });
    map.on("dragend", () => { userInteracting = false; });

    map.on("load", () => {
      // ── Atmospheric glow / space background ─────────────────────────────
      map.setFog({
        "color": "rgb(100, 175, 240)",
        "high-color": "rgb(20,  80,  180)",
        "horizon-blend": 0.06,
        "space-color": "rgb(5,   5,   18)",
        "star-intensity": 0.90,
      });

      map.addSource("env-anomalies", {
        type: "geojson",
        data: buildGeoJSON(CITY_CONFIG.mumbai),
      });

      map.addLayer({
        id: "env-heat",
        type: "heatmap",
        source: "env-anomalies",
        maxzoom: 18,
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["get", "severity"], 0, 0, 1, 1],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 4, 0.7, 12, 2.4],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 4, 26, 12, 72],
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.9, 16, 0.45],
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

      map.addLayer({
        id: "env-circles",
        type: "circle",
        source: "env-anomalies",
        minzoom: 8,
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

      map.on("click", "env-circles", (event) => {
        const feature = event.features?.[0];
        if (!feature?.properties?.zone) return;

        const zone = JSON.parse(feature.properties.zone);
        onZoneClickRef.current?.(zone);

        map.flyTo({
          center: feature.geometry.coordinates,
          zoom: 12.5,
          duration: 900,
          essential: true,
        });
      });

      map.on("mouseenter", "env-circles", () => {
        map.getCanvas().style.cursor = "crosshair";
      });

      map.on("mouseleave", "env-circles", () => {
        map.getCanvas().style.cursor = "crosshair";
      });

      // ── Flush any city click that arrived before map was ready ─────────
      if (pendingCityRef.current) {
        const city = pendingCityRef.current;
        pendingCityRef.current = null;
        const src = map.getSource("env-anomalies");
        if (src) src.setData(buildGeoJSON(city));
        map.flyTo({ center: city.center, zoom: city.zoom ?? 11, duration: 2200, essential: true, curve: 1.8, speed: 0.7 });
      }
    });

    return () => {
      spinEnabledRef.current = false;
      clearInterval(spinTimer);
      map.remove();
      mapRef.current = null;
    };
  }, [containerRef]); // ← do NOT include activeCity here — city changes are handled by the flyTo effect below

  // ── Fly to city whenever activeCity changes ────────────────────────────────
  useEffect(() => {
    if (!activeCity) return;
    const city = CITY_CONFIG[activeCity];
    if (!city) return;

    const doFly = (map) => {
      try {
        // Kill the globe spin FIRST — rotateTo cancels flyTo if it fires during animation
        spinEnabledRef.current = false;
        const source = map.getSource("env-anomalies");
        if (source) source.setData(buildGeoJSON(city));
        map.flyTo({ center: city.center, zoom: city.zoom ?? 11, duration: 2200, essential: true, curve: 1.8, speed: 0.7 });
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

    const primaryLayer = Object.entries(activeLayers).find(([, value]) => value)?.[0] || "all";
    const gradient = LAYER_CONFIG[primaryLayer]?.gradient || LAYER_CONFIG.all.gradient;

    const colorExpr = [
      "interpolate", ["linear"], ["heatmap-density"],
      ...Object.entries(gradient).flatMap(([stop, color]) => [Number(stop), color]),
    ];

    if (map.isStyleLoaded() && map.getLayer("env-heat")) {
      map.setPaintProperty("env-heat", "heatmap-color", colorExpr);
    }
  }, [activeLayers]);

  return mapRef;
}

import { useState, useRef, useCallback, useEffect } from "react";

// ── Styles ────────────────────────────────────────────────────────────────
import "./styles/globals.css";

// ── Hooks ─────────────────────────────────────────────────────────────────
import { useClock, useToast, useIntro, useMapbox } from "./hooks";

// ── Constants ─────────────────────────────────────────────────────────────
import { CITY_CONFIG } from "./constants/cities";
import { LAYER_CONFIG } from "./constants/layers";

// ── Utils ─────────────────────────────────────────────────────────────────
import { generateTrend } from "./utils/helpers";

// ── Map ───────────────────────────────────────────────────────────────────
import IntroOverlay from "./components/map/IntroOverlay";

// ── Panels ────────────────────────────────────────────────────────────────
import TopBar from "./components/panels/TopBar";
import LayerControls from "./components/panels/LayerControls";
import InsightPanel from "./components/panels/InsightPanel";
import BottomBar from "./components/panels/BottomBar";

// ── HUD ───────────────────────────────────────────────────────────────────
import HUDCorners from "./components/hud/HUDCorners";
import StatusBar from "./components/hud/StatusBar";
import Toast from "./components/hud/Toast";

// ─────────────────────────────────────────────────────────────────────────────
// App — root component
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const defaultCity = CITY_CONFIG.mumbai;

  // ── Intro & panel visibility ─────────────────────────────────────────────
  const { phase: introPhase, panelsVisible } = useIntro();

  // ── Live clock ───────────────────────────────────────────────────────────
  const recTime = useClock();

  // ── Toast ────────────────────────────────────────────────────────────────
  const { message: toastMsg, phase: toastPhase, show: showToast } = useToast();

  // ── City & layer state ───────────────────────────────────────────────────
  const [activeCity, setActiveCity] = useState(null);   // starts on globe view
  const [activeLayers, setActiveLayers] = useState({
    air: true,
    water: false,
    land: false,
    all: false,
  });
  const [coords, setCoords] = useState({
    lat: "20.5937",
    lng: "78.9629",
  });

  // ── Insight panel state ──────────────────────────────────────────────────
  const [selectedZone, setSelectedZone] = useState(null);
  const [insightOpen, setInsightOpen] = useState(false);
  const [trendData, setTrendData] = useState([]);

  // ── Mapbox container ref (used in production) ────────────────────────────
  const mapContainerRef = useRef(null);

  // Production Mapbox integration (stubs until token + npm package added)
  useMapbox({
    containerRef: mapContainerRef,
    activeCity,
    activeLayers,
    onZoneClick: handleZoneClick,
  });

  // ── Handlers ─────────────────────────────────────────────────────────────

  function handleCitySelect(cityId) {
    if (activeCity === cityId) return;

    setSelectedZone(null);
    setInsightOpen(false);
    setActiveCity(cityId);

    const city = CITY_CONFIG[cityId];
    setCoords({
      lat: city.center[1].toFixed(4),
      lng: city.center[0].toFixed(4),
    });

    showToast(`SCANNING ${city.label.toUpperCase()} // ANOMALY DETECTION ACTIVE`);
  }

  function handleZoneClick(zone) {
    setSelectedZone(zone);
    setTrendData(generateTrend(zone.severity));
    setInsightOpen(true);
    showToast(`ANOMALY DETECTED // ${zone.name.toUpperCase()}`);
  }

  function handleInsightClose() {
    setInsightOpen(false);
    setTimeout(() => setSelectedZone(null), 420); // wait for slide-out
  }

  const handleLayerToggle = useCallback((layerId) => {
    setActiveLayers((prev) => {
      const next = { ...prev, [layerId]: !prev[layerId] };
      // Ensure at least one layer is always on
      if (!Object.values(next).some(Boolean)) return prev;
      return next;
    });
  }, []);

  const handleParamChange = useCallback((paramName, value) => {
    // Wire up to Mapbox layer paint properties in production
    // e.g. map.setPaintProperty('env-heat', 'heatmap-radius', value * 0.8)
    console.debug("[GeoSense] param change:", paramName, value);
  }, []);

  // Prevent browser-level zoom (Ctrl/Cmd + wheel / +/- / 0)
  // so only the map surface performs zoom interactions.
  useEffect(() => {
    const preventBrowserWheelZoom = (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
      }
    };

    const preventBrowserKeyZoom = (event) => {
      const isZoomKey = ["+", "-", "=", "0"].includes(event.key);
      if ((event.ctrlKey || event.metaKey) && isZoomKey) {
        event.preventDefault();
      }
    };

    window.addEventListener("wheel", preventBrowserWheelZoom, { passive: false });
    window.addEventListener("keydown", preventBrowserKeyZoom);

    return () => {
      window.removeEventListener("wheel", preventBrowserWheelZoom);
      window.removeEventListener("keydown", preventBrowserKeyZoom);
    };
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        position: "relative",
        width: "100vw",
        height: "100vh",
        overflow: "hidden",
        background: "#0b0f14",
      }}
      className="scanlines vignette"
    >
      {/* Grain texture */}
      <div className="grain" />

      {/* ── Real Mapbox map container ───────────────────────────────────── */}
      <div ref={mapContainerRef} style={{ position: "absolute", inset: 0, zIndex: 0 }} />

      {/* ── Intro overlay ────────────────────────────────────────────────── */}
      <IntroOverlay phase={introPhase} />

      {/* ── HUD corners ──────────────────────────────────────────────────── */}
      <HUDCorners />

      {/* ── Panels (visible after intro) ─────────────────────────────────── */}
      {panelsVisible && (
        <>
          <TopBar
            activeLayers={activeLayers}
            recTime={recTime}
            coords={coords}
          />

          {/* Layer controls hide when insight panel is open */}
          {!insightOpen && (
            <LayerControls
              activeLayers={activeLayers}
              onToggleLayer={handleLayerToggle}
              onParamChange={handleParamChange}
            />
          )}

          <InsightPanel
            zone={selectedZone}
            trendData={trendData}
            isOpen={insightOpen}
            onClose={handleInsightClose}
          />

          <BottomBar
            activeCity={activeCity}
            onSelectCity={handleCitySelect}
          />
        </>
      )}

      {/* ── Toast ────────────────────────────────────────────────────────── */}
      <Toast message={toastMsg} phase={toastPhase} />

      {/* ── Status bar ───────────────────────────────────────────────────── */}
      {panelsVisible && (
        <StatusBar activeCity={activeCity} recTime={recTime} />
      )}
    </div>
  );
}

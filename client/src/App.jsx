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
import DeepAnalysisOverlay from "./components/panels/DeepAnalysisOverlay";
import BottomBar from "./components/panels/BottomBar";

// ── HUD ───────────────────────────────────────────────────────────────────
import HUDCorners from "./components/hud/HUDCorners";
import StatusBar from "./components/hud/StatusBar";
import Toast from "./components/hud/Toast";

// ─────────────────────────────────────────────────────────────────────────────
// App — root component
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  // ── Intro & panel visibility ─────────────────────────────────────────────
  const { phase: introPhase, panelsVisible } = useIntro();

  // ── Live clock ───────────────────────────────────────────────────────────
  const recTime = useClock();

  // ── Toast ────────────────────────────────────────────────────────────────
  const { message: toastMsg, phase: toastPhase, show: showToast } = useToast();

  // ── City & layer state ───────────────────────────────────────────────────
  const [activeCity, setActiveCity] = useState(null);   // starts on India overview
  const [activeLayers, setActiveLayers] = useState({
    aqi: true,
    ndvi: false,
    ndwi: false,
    lst: false,
    all: false,
  });
  const [coords, setCoords] = useState({
    lat: "20.5937",
    lng: "78.9629",
  });

  // ── Insight panel state ──────────────────────────────────────────────────
  const [selectedZone, setSelectedZone] = useState(null);
  const [insightOpen, setInsightOpen] = useState(false);
  const [deepAnalysisOpen, setDeepAnalysisOpen] = useState(false);
  const [trendData, setTrendData] = useState([]);
  const [layerControlsVisible, setLayerControlsVisible] = useState(false);
  const [isLeavingCity, setIsLeavingCity] = useState(false);
  const activeCityLabel = activeCity ? CITY_CONFIG[activeCity]?.label : null;

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
    if (cityId === "india") {
      // Start zoom-out and fade-out simultaneously
      setSelectedZone(null);
      setInsightOpen(false);
      setDeepAnalysisOpen(false);
      setIsLeavingCity(true);
      setLayerControlsVisible(false);
      setActiveCity(null); // Start map zoom-out immediately

      setTimeout(() => {
        setIsLeavingCity(false); // Remove mask fade animation
        setCoords({
          lat: "22.0000",
          lng: "79.0000",
        });
        showToast("RETURNED TO PAN-INDIA OVERVIEW // NATIONAL SWEEP ACTIVE");
      }, 700);
      return;
    }

    if (activeCity === cityId) return;

    setSelectedZone(null);
    setInsightOpen(false);
    setDeepAnalysisOpen(false);
    setLayerControlsVisible(false);
    setIsLeavingCity(false);
    setActiveCity(cityId);

    const city = CITY_CONFIG[cityId];
    setCoords({
      lat: city.center[1].toFixed(4),
      lng: city.center[0].toFixed(4),
    });

    showToast(`SCANNING ${city.label.toUpperCase()} // ANOMALY DETECTION ACTIVE`);

    // Show layer controls after zoom animation (700ms)
    setTimeout(() => {
      setLayerControlsVisible(true);
    }, 700);
  }

  function handleZoneClick(zone) {
    setSelectedZone(zone);
    setTrendData(generateTrend(zone.severity));
    setInsightOpen(true);
    setDeepAnalysisOpen(false);
    showToast(`ANOMALY DETECTED // ${zone.name.toUpperCase()}`);
  }

  function handleInsightClose() {
    setInsightOpen(false);
    setDeepAnalysisOpen(false);
    setTimeout(() => setSelectedZone(null), 420); // wait for slide-out
  }

  function handleDeepAnalysisOpen() {
    if (!selectedZone) return;
    setDeepAnalysisOpen(true);
  }

  function handleDeepAnalysisClose() {
    setDeepAnalysisOpen(false);
  }

  const handleLayerToggle = useCallback((layerId) => {
    setActiveLayers((prev) => {
      if (layerId === "all") {
        const isCurrentlyActive = prev.all;
        if (isCurrentlyActive) {
          // Toggle off all layers
          return {
            aqi: false,
            ndvi: false,
            ndwi: false,
            lst: false,
            all: false,
          };
        } else {
          // Toggle on all layers
          return {
            aqi: true,
            ndvi: true,
            ndwi: true,
            lst: true,
            all: true,
          };
        }
      }

      // Individual layer toggle: if already active, turn it off; otherwise activate it
      const isCurrentlyActive = prev[layerId];
      if (isCurrentlyActive) {
        // Toggle off — show base map only
        return {
          aqi: false,
          ndvi: false,
          ndwi: false,
          lst: false,
          all: false,
        };
      } else {
        // Toggle on — single-select
        return {
          aqi: layerId === "aqi",
          ndvi: layerId === "ndvi",
          ndwi: layerId === "ndwi",
          lst: layerId === "lst",
          all: false,
        };
      }
    });

    const layerLabel = LAYER_CONFIG[layerId]?.label || "Layer";
    const action = activeLayers[layerId] ? "DEACTIVATED" : "ACTIVATED";
    showToast(`${layerLabel.toUpperCase()} LAYER ${action}`);
  }, [showToast, activeLayers]);

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

      {/* ── Satellite circular mask overlays ─────────────────────────────── */}
      {(activeCity || isLeavingCity) && (
        <div
          className="satellite-mask"
          style={isLeavingCity ? { animation: "fadeOutMask 0.7s ease-in-out forwards" } : { animation: "fadeInMask 0.7s ease-in-out forwards" }}
        />
      )}

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

          {/* Layer controls on left — appears after city animation */}
          {layerControlsVisible && (
            <LayerControls
              activeLayers={activeLayers}
              onToggleLayer={handleLayerToggle}
            />
          )}

          {/* Insight panel on right */}
          <InsightPanel
            zone={selectedZone}
            cityLabel={activeCityLabel}
            trendData={trendData}
            activeLayers={activeLayers}
            isOpen={insightOpen}
            onClose={handleInsightClose}
            onDeepAnalysis={handleDeepAnalysisOpen}
          />

          <DeepAnalysisOverlay
            zone={selectedZone}
            cityLabel={activeCityLabel}
            trendData={trendData}
            activeLayers={activeLayers}
            isOpen={deepAnalysisOpen}
            onClose={handleDeepAnalysisClose}
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

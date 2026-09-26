import { useState, useRef, useCallback, useEffect } from "react";

// ── Styles ────────────────────────────────────────────────────────────────
import "./styles/globals.css";

// ── Hooks ─────────────────────────────────────────────────────────────────
import { useClock, useToast, useIntro, useMapbox } from "./hooks";
import { useGeoSenseData, useZoneExplanation } from "./hooks/useGeoSenseData";

// ── Constants ─────────────────────────────────────────────────────────────
import { CITY_CONFIG } from "./constants/cities";
import { LAYER_CONFIG } from "./constants/layers";

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
import Toast from "./components/hud/Toast"; import ClassificationHeader from "./components/hud/ClassificationHeader";
import OrbitalPass from "./components/hud/OrbitalPass";
import TelemetryOverlay from "./components/hud/TelemetryOverlay";
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
    water_health: false,
    lst: false,
    all: false,
  });
  const [coords, setCoords] = useState({
    lat: "20.5937",
    lng: "78.9629",
  });

  // ── Insight panel state ──────────────────────────────────────────────────
  const [selectedZone, setSelectedZone] = useState(null);
  const [pointAnalysis, setPointAnalysis] = useState(null);
  const [insightOpen, setInsightOpen] = useState(false);
  const [deepAnalysisOpen, setDeepAnalysisOpen] = useState(false);
  const [layerControlsVisible, setLayerControlsVisible] = useState(false);
  const [isLeavingCity, setIsLeavingCity] = useState(false);
  const activeCityLabel = activeCity ? CITY_CONFIG[activeCity]?.label : null;

  // ── Data Fetching ────────────────────────────────────────────────────────
  const { zones: liveZones, liveMunicipalities, waterBodies, aqiSurface, ndviSurface, lstSurface, waterHealthSurface, boundary: liveBoundary, loading: zonesLoading, error: zonesError } = useGeoSenseData(activeCity);
  const { explanationData, explanationLoading, fetchExplanation, clearExplanation } = useZoneExplanation();

  // ── Mapbox container ref (used in production) ────────────────────────────
  const mapContainerRef = useRef(null);

  // Production Mapbox integration (stubs until token + npm package added)
  useMapbox({
    containerRef: mapContainerRef,
    activeCity,
    activeLayers,
    onZoneClick: handleZoneClick,
    onPointAnalysis: (zone, analysis) => handleZoneClick(zone, analysis),
    liveMunicipalities,
    waterBodies,
    aqiSurface,
    ndviSurface,
    lstSurface,
    waterHealthSurface,
    boundary: liveBoundary,
  });

  // ── Handlers ─────────────────────────────────────────────────────────────

  function handleCitySelect(cityId) {
    if (cityId === "india") {
      // Start zoom-out and fade-out simultaneously
      setSelectedZone(null);
      setPointAnalysis(null);
      clearExplanation();
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
    setPointAnalysis(null);
    clearExplanation();
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

  function handleZoneClick(zone, analysisData) {
    setSelectedZone(zone);
    if (analysisData) {
      setPointAnalysis(analysisData);
    } else {
      setPointAnalysis(zone?.pointAnalysis || null);
    }
    // Use cell-level ID (from spatial_cells) for explanation when available
    const resolvedId = analysisData?.cell?.id || zone?.pointAnalysis?.cell?.id || zone.id;
    if (resolvedId && !String(resolvedId).startsWith("mum-") && !String(resolvedId).startsWith("blr-") && !String(resolvedId).startsWith("del-")) {
      // Real backend zone / cell ID
      const pixelLst = analysisData?.pixel?.lst?.value_c
        ?? zone?.pointAnalysis?.pixel?.lst?.value_c
        ?? (zone.pixelLST && !zone.pixelLST.nodata ? zone.pixelLST.value_c : null);
      fetchExplanation(resolvedId, pixelLst);
    } else {
      // Placeholder UI zone - no real backend data
      clearExplanation();
    }
    setInsightOpen(true);
    setDeepAnalysisOpen(false);
    const muniName = analysisData?.municipality?.name
      || zone?.pointAnalysis?.municipality?.name
      || zone.name;
    showToast(`LOCATION SCANNED // ${muniName.toUpperCase()}`);
  }

  function handleInsightClose() {
    setInsightOpen(false);
    setDeepAnalysisOpen(false);
    setTimeout(() => {
      setSelectedZone(null);
      setPointAnalysis(null);
      clearExplanation();
    }, 420); // wait for slide-out
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
            water_health: false,
            lst: false,
            all: false,
          };
        } else {
          // Toggle on all layers
          return {
            aqi: true,
            ndvi: true,
            water_health: true,
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
          water_health: false,
          lst: false,
          all: false,
        };
      } else {
        // Toggle on — single-select
        return {
          aqi: layerId === "aqi",
          ndvi: layerId === "ndvi",
          water_health: layerId === "water_health",
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
            pointAnalysis={pointAnalysis}
            cityLabel={activeCityLabel}
            explanationData={explanationData}
            activeLayers={activeLayers}
            isOpen={insightOpen}
            onClose={handleInsightClose}
            onDeepAnalysis={handleDeepAnalysisOpen}
          />

          <DeepAnalysisOverlay
            zone={selectedZone}
            pointAnalysis={pointAnalysis}
            cityLabel={activeCityLabel}
            explanationData={explanationData}
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

      {/* ── Intelligence Agency Overlays ─────────────────────────────────── */}
      {panelsVisible && activeCity && (
        <>
          <ClassificationHeader />
          <OrbitalPass recTime={recTime} />
          <TelemetryOverlay coords={coords} />
        </>
      )}

      {/* ── Status bar ───────────────────────────────────────────────────── */}
      {panelsVisible && (
        <StatusBar activeCity={activeCity} recTime={recTime} />
      )}
    </div>
  );
}

import { useState, useRef, useCallback, useEffect } from "react";

// ── Styles ────────────────────────────────────────────────────────────────
import "./styles/globals.css";

// ── Hooks ─────────────────────────────────────────────────────────────────
import { useClock, useToast, useIntro, useMapbox } from "./hooks";
import { useGeoSenseData, useZoneExplanation } from "./hooks/useGeoSenseData";

// ── Constants ─────────────────────────────────────────────────────────────
import { CITY_CONFIG } from "./constants/cities";
import { LAYER_CONFIG } from "./constants/layers";
import { getApiUrl, setApiCity } from "./utils/api";

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
import ClassificationHeader from "./components/hud/ClassificationHeader";
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
  const [activeCity, setActiveCity] = useState(null); // starts on India overview
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
  // where the user last clicked; answered = that click's analysis has arrived
  const [clickPoint, setClickPoint] = useState(null);
  const closeTimerRef = useRef(null);
  const [layerControlsVisible, setLayerControlsVisible] = useState(false);
  const [isLeavingCity, setIsLeavingCity] = useState(false);
  const activeCityLabel = activeCity ? CITY_CONFIG[activeCity]?.label : null;
  // every /api/ request from here on is for the city on screen
  setApiCity(activeCity);

  // ── Data Fetching ────────────────────────────────────────────────────────
  const {
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
    boundary: liveBoundary,
  } = useGeoSenseData(activeCity);
  const {
    explanationData,
    explanationLoading,
    aiPending,
    fetchExplanation,
    clearExplanation,
  } = useZoneExplanation();

  // The layer the user is looking at ("composite" when all layers are on).
  const focusLayer = activeLayers.all
    ? "composite"
    : ["aqi", "ndvi", "water_health", "lst"].find((k) => activeLayers[k]) || "composite";

  // Load a layer's heatmap images only once it has been switched on. Previously all five
  // layers (~15 MB of PNGs, 12 large GPU textures) were downloaded at start-up.
  const [loadedLayers, setLoadedLayers] = useState({});
  useEffect(() => {
    const anyOn = activeLayers.all || ["aqi", "ndvi", "water_health", "lst"].some((k) => activeLayers[k]);
    if (anyOn && !loadedLayers[focusLayer]) {
      setLoadedLayers((prev) => ({ ...prev, [focusLayer]: true }));
    }
  }, [activeLayers, focusLayer, loadedLayers]);

  // The clicked area's value on the active layer (same number as the panel's big value: the 300 m
  // area, else the exact point) -> a pointer on the legend bar.
  const legendValue = (() => {
    if (!insightOpen || !pointAnalysis) return null;
    const m = pointAnalysis.cell?.metrics || {};
    const px = pointAnalysis.pixel || {};
    const pt = (b, f = "value") => (b && !b.nodata ? b[f] ?? null : null);
    if (focusLayer === "aqi") return m.aqi ?? pt(px.aqi);
    if (focusLayer === "ndvi") return m.ndvi_land ?? m.ndvi ?? pt(px.ndvi);
    if (focusLayer === "lst") return m.lst ?? pt(px.lst, "value_c");
    if (focusLayer === "water_health") return m.water_health_score ?? pt(px.water_health);
    return m.composite ?? pt(px.composite);
  })();

  // Keep the right panel on the map's layer: switching layers while a point is open reloads
  // that point's write-up for the new layer (evidence only - fast; the AI summary stays in
  // Deep Analysis).
  const panelFocusRef = useRef(null);
  useEffect(() => {
    if (!insightOpen || deepAnalysisOpen) return;
    const lon = pointAnalysis?.location?.longitude ?? selectedZone?.coords?.[0];
    const lat = pointAnalysis?.location?.latitude ?? selectedZone?.coords?.[1];
    if (!(Number.isFinite(lon) && Number.isFinite(lat) && pointAnalysis?.cell)) return;
    if (explanationData?.focus === focusLayer) return;
    const key = `${lon},${lat},${focusLayer}`;
    if (panelFocusRef.current === key) return;
    panelFocusRef.current = key;
    fetchExplanation(lon, lat, focusLayer, false, { keep: !!explanationData });
  }, [insightOpen, deepAnalysisOpen, focusLayer, explanationData, pointAnalysis, selectedZone, fetchExplanation]);

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
    aqiSurface: loadedLayers.aqi ? aqiSurface : null,
    ndviSurface: loadedLayers.ndvi ? ndviSurface : null,
    lstSurface: loadedLayers.lst ? lstSurface : null,
    waterHealthSurface: loadedLayers.water_health ? waterHealthSurface : null,
    compositeSurface: loadedLayers.composite ? compositeSurface : null,
    boundary: liveBoundary,
    // The pin drops where you clicked straight away ("Scanning…"), then shows the place name
    // when the answer for THAT click arrives.
    markerPoint: clickPoint
      ? (clickPoint.answered
        ? {
            longitude: clickPoint.longitude,
            latitude: clickPoint.latitude,
            label: pointAnalysis?.place?.label || selectedZone?.name || pointAnalysis?.municipality?.name,
          }
        : { longitude: clickPoint.longitude, latitude: clickPoint.latitude, label: "Scanning…", pending: true })
      : null,
    onPointPending: (lng, lat) => {
      clearTimeout(closeTimerRef.current);
      setClickPoint({ longitude: lng, latitude: lat, answered: false });
    },
  });

  // After the first layer is on screen, quietly download the other layers' heatmap images
  // into the browser cache, so switching layers later is instant (they are not drawn until used).
  useEffect(() => {
    const anyLoaded = Object.keys(loadedLayers).length > 0;
    if (!anyLoaded) return undefined;
    const surfaces = { aqi: aqiSurface, ndvi: ndviSurface, lst: lstSurface, water_health: waterHealthSurface, composite: compositeSurface };
    const t = setTimeout(() => {
      Object.entries(surfaces).forEach(([k, srf]) => {
        if (!srf || loadedLayers[k]) return;
        [srf.sharp_url || srf.image_url, srf.glow_url, srf.halo_url].filter(Boolean).forEach((u) => {
          const img = new Image();
          // CORS mode, like the map's own request, so the cached copy is reusable by the map
          img.crossOrigin = "anonymous";
          img.decoding = "async";
          img.src = getApiUrl(u);
        });
      });
    }, 2500);
    return () => clearTimeout(t);
  }, [loadedLayers, aqiSurface, ndviSurface, lstSurface, waterHealthSurface, compositeSurface]);

  // ── Handlers ─────────────────────────────────────────────────────────────

  function handleCitySelect(cityId) {
    if (cityId === "india") {
      // Start zoom-out and fade-out simultaneously
      setSelectedZone(null);
      setPointAnalysis(null);
      clearExplanation();
      setInsightOpen(false);
      setDeepAnalysisOpen(false);
      setClickPoint(null);
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
    setClickPoint(null);
    setLayerControlsVisible(false);
    setIsLeavingCity(false);
    setActiveCity(cityId);

    const city = CITY_CONFIG[cityId];
    setCoords({
      lat: city.center[1].toFixed(4),
      lng: city.center[0].toFixed(4),
    });

    showToast(
      `SCANNING ${city.label.toUpperCase()} // ANOMALY DETECTION ACTIVE`,
    );

    // Show layer controls after zoom animation (700ms)
    setTimeout(() => {
      setLayerControlsVisible(true);
    }, 700);
  }

  function handleZoneClick(zone, analysisData) {
    // a close that is still sliding out must not wipe this new click's data when its timer fires
    clearTimeout(closeTimerRef.current);
    setClickPoint((p) => (p ? { ...p, answered: true } : p));
    setSelectedZone(zone);
    if (analysisData) {
      setPointAnalysis(analysisData);
    } else {
      setPointAnalysis(zone?.pointAnalysis || null);
    }
    // Explanation = evidence (pixel → 300 m cell → municipality) + ML signals + RAG.
    const lon = analysisData?.location?.longitude ?? zone?.coords?.[0];
    const lat = analysisData?.location?.latitude ?? zone?.coords?.[1];
    if (Number.isFinite(lon) && Number.isFinite(lat) && analysisData?.cell) {
      panelFocusRef.current = `${lon},${lat},${focusLayer}`;
      fetchExplanation(lon, lat, focusLayer, false);
    } else {
      clearExplanation();
    }
    setInsightOpen(true);
    setDeepAnalysisOpen(false);
    const muniName =
      analysisData?.municipality?.name ||
      zone?.pointAnalysis?.municipality?.name ||
      zone?.name ||
      "Location";
    showToast(`LOCATION SCANNED // ${String(muniName).toUpperCase()}`);
  }

  function handleInsightClose() {
    setInsightOpen(false);
    setDeepAnalysisOpen(false);
    setClickPoint(null);
    clearTimeout(closeTimerRef.current);
    closeTimerRef.current = setTimeout(() => {
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
    // Deep Analysis tabs may have loaded another layer's write-up; let the right panel
    // reload the map layer's one.
    panelFocusRef.current = null;
    setDeepAnalysisOpen(false);
  }

  const handleLayerToggle = useCallback(
    (layerId) => {
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
        const isCurrentlyActive = prev[layerId] && !prev.all;
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
    },
    [showToast, activeLayers],
  );

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

    window.addEventListener("wheel", preventBrowserWheelZoom, {
      passive: false,
    });
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
      <div
        ref={mapContainerRef}
        style={{ position: "absolute", inset: 0, zIndex: 0 }}
      />

      {/* ── Satellite circular mask overlays ─────────────────────────────── */}
      {(activeCity || isLeavingCity) && (
        <div
          className="satellite-mask"
          style={
            isLeavingCity
              ? { animation: "fadeOutMask 0.7s ease-in-out forwards" }
              : { animation: "fadeInMask 0.7s ease-in-out forwards" }
          }
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
              aqiSurfaceStatus={aqiSurfaceStatus}
              aqiSurfaceInfo={aqiSurfaceInfo}
              provenance={provenance}
            />
          )}

          {/* Insight panel on right */}
          <InsightPanel
            zone={selectedZone}
            pointAnalysis={pointAnalysis}
            cityLabel={activeCityLabel}
            explanationData={explanationData}
            activeLayers={activeLayers}
            focusLayer={focusLayer}
            isOpen={insightOpen}
            onClose={handleInsightClose}
            onDeepAnalysis={handleDeepAnalysisOpen}
          />

          <DeepAnalysisOverlay
            zone={selectedZone}
            pointAnalysis={pointAnalysis}
            cityLabel={activeCityLabel}
            explanationData={explanationData}
            explanationLoading={explanationLoading}
            aiPending={aiPending}
            activeLayers={activeLayers}
            isOpen={deepAnalysisOpen}
            onClose={handleDeepAnalysisClose}
            provenance={provenance}
            mlSummary={mlSummary}
            onFocusChange={async (focus) => {
              const lon = pointAnalysis?.location?.longitude ?? selectedZone?.coords?.[0];
              const lat = pointAnalysis?.location?.latitude ?? selectedZone?.coords?.[1];
              if (!(Number.isFinite(lon) && Number.isFinite(lat) && pointAnalysis?.cell)) return;
              // 1) evidence for this layer straight away (fast), unless it is already on screen;
              // 2) then the AI plain-words summary, while the evidence stays visible.
              if (explanationData?.focus !== focus) {
                await fetchExplanation(lon, lat, focus, false, { keep: !!explanationData });
              }
              fetchExplanation(lon, lat, focus, true, { keep: true });
            }}
          />

          <BottomBar
            activeCity={activeCity}
            onSelectCity={handleCitySelect}
            activeLayers={activeLayers}
            ndviSurface={ndviSurface}
            waterHealthSurface={waterHealthSurface}
            aqiSurface={aqiSurface}
            lstSurface={lstSurface}
            compositeSurface={compositeSurface}
            markerValue={legendValue}
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
      {panelsVisible && <StatusBar activeCity={activeCity} recTime={recTime} />}
    </div>
  );
}

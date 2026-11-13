import AIInsightSection from "./AIInsightSection";
import {
  getAqiCpcbBand,
  getLstBand,
  getNdviBand,
  getSeverityColor,
  getSeverityLabel,
  getZoneMetrics,
  normalizeMetric,
} from "../../utils/helpers";
import {
  waterBandFromPercentile,
  waterPercentileFromExplanation,
} from "../../utils/helpers";
import RootCauseBar from "../ui/RootCauseBar";

const LAYER_PRIORITY = ["aqi", "ndvi", "water_health", "lst"];
const COMPOSITE_ACCENT_COLOR = "#ff8a3d";

const LAYER_META = {
  aqi: { icon: "○", label: "AQI", color: "#ff8c00" },
  ndvi: { icon: "◇", label: "NDVI", color: "#1dd1a1" },
  water_health: { icon: "◈", label: "Water Health", color: "#00b4d8" },
  lst: { icon: "▣", label: "LST", color: "#ff5f57" },
};

// Composite v2 components (see server/app/services/composite_v2.py)
const COMPONENT_META = {
  heat: { icon: "▣", label: "Heat", sub: "LST", color: "#ff5f57" },
  surface: {
    icon: "◇",
    label: "Surface",
    sub: "vegetation on land · Water Health on water",
    color: "#1dd1a1",
  },
  air: { icon: "○", label: "Air", sub: "AQI", color: "#ff8c00" },
};

function resolveActiveLayerId(activeLayers) {
  if (!activeLayers) return "aqi";
  if (activeLayers.all) return "all";
  const selected = LAYER_PRIORITY.filter((layerId) => activeLayers[layerId]);
  if (selected.length > 1) return "all";
  if (selected.length === 1) return selected[0];
  return "aqi";
}

function fmt(layerId, v) {
  if (v == null || !Number.isFinite(Number(v))) return null;
  const n = Number(v);
  if (layerId === "aqi") return String(Math.round(n));
  if (layerId === "ndvi") return n.toFixed(2);
  if (layerId === "lst") return n.toFixed(1);
  if (layerId === "water_health") return n.toFixed(2);
  if (layerId === "all") return String(Math.round(n));
  return String(n);
}

// ─────────────────────────────────────────────────────────────────────────────
// InsightPanel — slides in from the right when a point is clicked.
//   Top:    place, municipality, the 300 m area value of the map's layer (big), severity,
//           intensity, and the exact-point value.
//   Middle: insight summary (+ the composite breakdown on Composite).
//   Bottom: details — at this point · surrounding 300 m area · municipality.
// One layer on the map -> only that layer's data; Composite -> every layer.
// ─────────────────────────────────────────────────────────────────────────────

export default function InsightPanel({
  zone,
  pointAnalysis,
  cityLabel,
  explanationData: rawExplanation,
  activeLayers,
  focusLayer,
  isOpen,
  onClose,
  onDeepAnalysis,
}) {
  const metrics = zone ? getZoneMetrics(zone) : null;
  const activeLayerId = focusLayer
    ? focusLayer === "composite"
      ? "all"
      : focusLayer
    : resolveActiveLayerId(activeLayers);
  const isCompositeView = activeLayerId === "all";
  const activeLayerMeta = LAYER_META[activeLayerId] || LAYER_META.aqi;
  const focusKey = isCompositeView ? "composite" : activeLayerId;
  const show = (layerId) => isCompositeView || activeLayerId === layerId;
  // Composite lists only the layers that have a value here; a single-layer view keeps its own line
  const showPoint = (layerId, v) =>
    isCompositeView ? v != null : activeLayerId === layerId;
  // Use the write-up only when it was made for this layer (a layer switch refetches it).
  const explanationData =
    rawExplanation &&
    (rawExplanation._unavailable || rawExplanation.focus === focusKey)
      ? rawExplanation
      : null;

  const pixel = pointAnalysis?.pixel || zone?.pointAnalysis?.pixel || null;
  const cell = pointAnalysis?.cell || zone?.pointAnalysis?.cell || null;
  const municipality =
    pointAnalysis?.municipality || zone?.pointAnalysis?.municipality || null;
  const place = pointAnalysis?.place || zone?.pointAnalysis?.place || null;

  // exact point (pixel) values
  const pixelNdvi = pixel?.ndvi && !pixel.ndvi.nodata ? pixel.ndvi.value : null;
  const pixelLst = pixel?.lst && !pixel.lst.nodata ? pixel.lst.value_c : null;
  const pixelAqi = pixel?.aqi && !pixel.aqi.nodata ? pixel.aqi.value : null;
  const pixelWaterHealth =
    pixel?.water_health && !pixel.water_health.nodata
      ? pixel.water_health.value
      : null;
  const pixelComposite =
    pixel?.composite && !pixel.composite.nodata && pixel.composite.value != null
      ? pixel.composite.value * 100
      : null;
  const pixelOf = {
    aqi: pixelAqi,
    ndvi: pixelNdvi,
    lst: pixelLst,
    water_health: pixelWaterHealth,
    all: pixelComposite,
  };

  // 300 m area (cell) values — computed on click from the map's current layers
  const cellMetrics = cell?.metrics || {};
  const cellComposite =
    cellMetrics.composite != null ? cellMetrics.composite * 100 : null;
  const cellOf = {
    aqi: cellMetrics.aqi ?? metrics?.aqi ?? null,
    ndvi: cellMetrics.ndvi_land ?? cellMetrics.ndvi ?? metrics?.ndvi ?? null, // land only (water excluded)
    lst: cellMetrics.lst ?? metrics?.lst ?? null,
    water_health:
      cellMetrics.water_health_score ?? metrics?.water_health_score ?? null,
    all: cellComposite,
  };
  const cellAnomaly = cell?.anomaly || null;
  const breakdown = cellMetrics.composite_breakdown || null;

  // Main number: the 300 m area value; the exact point only when the area has no value.
  const areaValue = cellOf[activeLayerId];
  const pointValue = pixelOf[activeLayerId];
  const mainFromPoint = areaValue == null && pointValue != null;
  const mainValue = mainFromPoint ? pointValue : areaValue;
  const mainText = fmt(activeLayerId, mainValue) ?? "N/A";
  const mainUnit = activeLayerId === "lst" && mainValue != null ? "°C" : "";
  const mainCaption =
    mainValue == null
      ? "No value at this location"
      : mainFromPoint
        ? "At this exact point · no 300 m area average"
        : "300 m area average";
  const mainLabel = isCompositeView
    ? "Composite stress"
    : activeLayerMeta.label;
  const valueColor = isCompositeView
    ? COMPOSITE_ACCENT_COLOR
    : activeLayerMeta.color;

  const mainMetrics = {
    aqi: cellOf.aqi ?? pixelAqi,
    ndvi: cellOf.ndvi ?? pixelNdvi,
    lst: cellOf.lst ?? pixelLst,
    water_health_score: cellOf.water_health ?? pixelWaterHealth,
  };
  const stressValue = isCompositeView
    ? mainValue
    : normalizeMetric(activeLayerId, mainMetrics);
  const whPct = waterPercentileFromExplanation(explanationData);
  const severityScore = isCompositeView
    ? (mainValue ?? 0)
    : activeLayerId === "water_health" && whPct != null
      ? 100 - whPct
      : stressValue;
  const severityLabel = (() => {
    if (mainValue == null) return "NO DATA";
    if (activeLayerId === "aqi") return getAqiCpcbBand(mainValue);
    if (activeLayerId === "ndvi") return getNdviBand(mainValue);
    if (activeLayerId === "water_health")
      return waterBandFromPercentile(whPct) || "LOADING…";
    if (activeLayerId === "lst") return getLstBand(mainValue);
    return getSeverityLabel(severityScore);
  })();
  const severityColor =
    mainValue == null ? "var(--text-dim)" : getSeverityColor(severityScore);
  const severityScopeLabel = isCompositeView
    ? "Composite"
    : activeLayerId === "aqi"
      ? "AQI"
      : activeLayerMeta.label;

  const placeName =
    place?.label || zone?.name || municipality?.name || "Selected location";
  const placeTitle =
    cityLabel && !municipality?.name && !zone?.municipality_name
      ? `${placeName}, ${cityLabel}`
      : placeName;
  const muniName = municipality?.name || zone?.municipality_name || null;

  const classification = explanationData?.classification
    ? explanationData.classification.toUpperCase()
    : isCompositeView && (cellAnomaly?.flag || zone?.is_anomaly)
      ? "ANOMALY"
      : null;
  const pixelSource = isCompositeView
    ? pixel?.ndvi?.source || pixel?.lst?.source
    : pixel?.[activeLayerId]?.source;
  const gridCols = isCompositeView ? "1fr 1fr" : "1fr";

  return (
    <div
      style={{
        position: "fixed",
        top: 160,
        right: 16,
        bottom: 120,
        zIndex: 40,
        width: 380,
        transform: isOpen ? "translateX(0)" : "translateX(100%)",
        opacity: isOpen ? 1 : 0,
        transition:
          "transform 0.4s cubic-bezier(0.22,1,0.36,1), opacity 0.4s ease",
        display: "flex",
        flexDirection: "column",
        pointerEvents: isOpen ? "auto" : "none",
      }}
    >
      <div
        className="glass"
        style={{
          borderRadius: "12px",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {zone ? (
          <>
            {/* ── Top: place + main value ───────────────────────────────── */}
            <div
              style={{
                padding: "16px 18px 14px",
                borderBottom: "1px solid rgba(0,229,255,0.1)",
                position: "relative",
                flexShrink: 0,
              }}
            >
              <CloseButton onClick={onClose} />

              <div
                style={{
                  fontSize: "0.52rem",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  marginTop: 4,
                  marginBottom: 6,
                  color:
                    classification === "ANOMALY"
                      ? "rgba(255,59,59,0.75)"
                      : "rgba(0,229,255,0.5)",
                }}
              >
                {classification === "ANOMALY"
                  ? "● Anomaly detected"
                  : `${mainLabel} · location scan`}
              </div>

              <div
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontSize: "1.02rem",
                  fontWeight: 600,
                  color: "rgba(255,255,255,0.94)",
                  letterSpacing: "0.03em",
                  lineHeight: 1.35,
                  paddingRight: 28,
                }}
              >
                {placeTitle}
              </div>
              {muniName && !placeTitle.includes(muniName) && (
                <div
                  style={{
                    marginTop: 3,
                    fontSize: "0.62rem",
                    color: "var(--text-dim)",
                    letterSpacing: "0.08em",
                  }}
                >
                  Within {muniName}
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  justifyContent: "space-between",
                  marginTop: 14,
                  gap: 12,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: "0.56rem",
                      color: "var(--text-dim)",
                      letterSpacing: "0.16em",
                      textTransform: "uppercase",
                    }}
                  >
                    {mainLabel}
                  </div>
                  <div
                    style={{
                      fontSize: "0.56rem",
                      color: "rgba(255,255,255,0.5)",
                      letterSpacing: "0.06em",
                      marginTop: 3,
                    }}
                  >
                    {mainCaption}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 4,
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "'DM Mono', monospace",
                      fontSize: "2.6rem",
                      fontWeight: 600,
                      color: valueColor,
                      textShadow: `0 0 26px ${valueColor}66`,
                      lineHeight: 1,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    {mainText}
                  </span>
                  {mainUnit && (
                    <span
                      style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: "0.95rem",
                        fontWeight: 600,
                        color: valueColor,
                      }}
                    >
                      {mainUnit}
                    </span>
                  )}
                </div>
              </div>

              <div
                style={{
                  marginTop: 10,
                  fontSize: "0.58rem",
                  color: "var(--text-dim)",
                  letterSpacing: "0.1em",
                }}
              >
                {severityScopeLabel.toUpperCase()}:{" "}
                <span style={{ color: severityColor, fontWeight: 600 }}>
                  {severityLabel}
                </span>
              </div>
              <div
                style={{
                  marginTop: 7,
                  height: 3,
                  background: "rgba(255,255,255,0.06)",
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${stressValue == null ? 0 : Math.max(0, Math.min(100, stressValue))}%`,
                    background: valueColor,
                    boxShadow: `0 0 10px ${valueColor}88`,
                    borderRadius: 2,
                    transition: "width 1s cubic-bezier(0.22,1,0.36,1)",
                  }}
                />
              </div>

              {!mainFromPoint && (
                <div
                  style={{
                    marginTop: 9,
                    fontSize: "0.62rem",
                    color: "rgba(255,255,255,0.62)",
                  }}
                >
                  At this exact point:{" "}
                  <span
                    style={{
                      fontFamily: "'DM Mono', monospace",
                      color:
                        pointValue == null ? "var(--text-dim)" : valueColor,
                    }}
                  >
                    {pointValue == null
                      ? "no value"
                      : `${fmt(activeLayerId, pointValue)}${activeLayerId === "lst" ? " °C" : ""}`}
                  </span>
                </div>
              )}
            </div>

            {/* ── Body ─────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px 18px" }}>
              <SectionLabel>Insight summary</SectionLabel>
              <div
                style={{
                  borderLeft: "1px solid rgba(0,229,255,0.14)",
                  marginBottom: 16,
                  paddingLeft: 12,
                  color: "var(--text-dim)",
                  fontSize: "0.75rem",
                  lineHeight: 1.5,
                }}
              >
                <AIInsightSection explanationData={explanationData} compact />
              </div>

              {isCompositeView && (
                <>
                  <Divider />
                  <SectionLabel>
                    What drives the composite here (300 m area)
                  </SectionLabel>
                  {breakdown?.components &&
                  Object.keys(breakdown.components).length > 0 ? (
                    <>
                      {["heat", "surface", "air"]
                        .filter((k) => breakdown.components[k])
                        .map((k) => {
                          const c = breakdown.components[k];
                          const meta = COMPONENT_META[k];
                          return (
                            <RootCauseBar
                              key={k}
                              icon={meta.icon}
                              label={meta.label}
                              value={c ? c.value * 100 : null}
                              normalizedValue={c ? c.value * 100 : 0}
                              displayValue={
                                c ? `${Math.round(c.share_pct)}%` : "—"
                              }
                              color={meta.color}
                            />
                          );
                        })}
                      <div
                        style={{
                          fontSize: "0.54rem",
                          color: "var(--text-dim)",
                          lineHeight: 1.5,
                          marginTop: 2,
                        }}
                      >
                        Bar = how stressed each part is (0–100) · % = its share
                        of the score. Heat = LST · Surface = vegetation on land,
                        Water Health on water · Air = AQI.{" "}
                        {breakdown.coverage
                          ? `${breakdown.coverage} parts available here.`
                          : ""}
                      </div>
                    </>
                  ) : (
                    ["aqi", "ndvi", "water_health", "lst"]
                      .filter((k) => cellOf[k] != null)
                      .map((k) => (
                        <RootCauseBar
                          key={k}
                          icon={LAYER_META[k].icon}
                          label={
                            LAYER_META[k].label === "Water Health"
                              ? "Water"
                              : LAYER_META[k].label
                          }
                          value={cellOf[k]}
                          normalizedValue={
                            cellOf[k] == null
                              ? 0
                              : normalizeMetric(k, {
                                  aqi: cellOf.aqi,
                                  ndvi: cellOf.ndvi,
                                  lst: cellOf.lst,
                                  water_health_score: cellOf.water_health,
                                })
                          }
                          displayValue={
                            fmt(k, cellOf[k]) == null
                              ? "N/A"
                              : `${fmt(k, cellOf[k])}${k === "lst" ? "°C" : ""}`
                          }
                          color={LAYER_META[k].color}
                        />
                      ))
                  )}
                </>
              )}

              <Divider />
              <SectionLabel>Details</SectionLabel>

              {/* At this point (exact pixel of the map layer) */}
              {pixel && (
                <div style={{ marginBottom: 12 }}>
                  <SpatialLevelHeader
                    level="1"
                    label="At this point"
                    sublabel="Exact value from the map layer (10–30 m)"
                    accent="#ff5f57"
                  />
                  <div style={boxStyle("255, 95, 87", "#ff5f57")}>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: gridCols,
                        gap: "8px 12px",
                      }}
                    >
                      {showPoint("ndvi", pixelNdvi) && (
                        <MetricRow
                          label="NDVI"
                          value={
                            pixelNdvi != null
                              ? pixelNdvi.toFixed(3)
                              : pixel?.ndvi?.nodata
                                ? "No valid NDVI here"
                                : "N/A"
                          }
                          color="#1dd1a1"
                          nodata={pixel?.ndvi?.nodata}
                        />
                      )}
                      {showPoint("lst", pixelLst) && (
                        <MetricRow
                          label="LST"
                          value={
                            pixelLst != null
                              ? pixelLst.toFixed(1)
                              : pixel?.lst?.nodata
                                ? "No data"
                                : "N/A"
                          }
                          unit="°C"
                          color="#ff5f57"
                          nodata={pixel?.lst?.nodata}
                        />
                      )}
                      {showPoint("aqi", pixelAqi) && (
                        <MetricRow
                          label="AQI"
                          value={
                            pixelAqi != null
                              ? String(pixelAqi)
                              : pixel?.aqi?.nodata
                                ? "No data"
                                : "N/A"
                          }
                          color="#ff8c00"
                          nodata={pixel?.aqi?.nodata}
                        />
                      )}
                      {showPoint("water_health", pixelWaterHealth) && (
                        <MetricRow
                          label="Water Health"
                          value={
                            pixelWaterHealth != null
                              ? pixelWaterHealth.toFixed(3)
                              : pixel?.water_health?.nodata
                                ? "No water at this point"
                                : "N/A"
                          }
                          color="#00b4d8"
                          nodata={pixel?.water_health?.nodata}
                        />
                      )}
                    </div>
                    {pixelSource && (
                      <div
                        style={{
                          fontSize: "0.54rem",
                          color: "var(--text-dim)",
                          marginTop: 8,
                          letterSpacing: "0.06em",
                          lineHeight: 1.5,
                        }}
                      >
                        Source: {pixelSource}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Surrounding 300 m area (analytical cell) */}
              {cell && (
                <div style={{ marginBottom: 12 }}>
                  <SpatialLevelHeader
                    level="2"
                    label={`Surrounding ${cell.resolution_m || 300} m area`}
                    sublabel="Average over the grid square the models analyse"
                    accent="#1dd1a1"
                  />
                  <div style={boxStyle("29, 209, 161", "#1dd1a1")}>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: gridCols,
                        gap: "8px 12px",
                        marginBottom:
                          isCompositeView && cellAnomaly?.flag ? 10 : 0,
                      }}
                    >
                      {showPoint("aqi", cellOf.aqi) && (
                        <MetricRow
                          label="AQI"
                          value={
                            cellOf.aqi != null ? String(cellOf.aqi) : "N/A"
                          }
                          color="#ff8c00"
                        />
                      )}
                      {showPoint("ndvi", cellOf.ndvi) && (
                        <MetricRow
                          label="NDVI"
                          value={
                            cellOf.ndvi != null ? cellOf.ndvi.toFixed(2) : "N/A"
                          }
                          color="#1dd1a1"
                        />
                      )}
                      {showPoint("lst", cellOf.lst) && (
                        <MetricRow
                          label="LST"
                          value={
                            cellOf.lst != null ? cellOf.lst.toFixed(1) : "N/A"
                          }
                          unit="°C"
                          color="#ff5f57"
                        />
                      )}
                      {showPoint("water_health", cellOf.water_health) && (
                        <MetricRow
                          label="Water Health"
                          value={
                            cellOf.water_health != null
                              ? cellOf.water_health.toFixed(3)
                              : "No water in area"
                          }
                          color="#00b4d8"
                          nodata={cellOf.water_health == null}
                        />
                      )}
                    </div>
                    {isCompositeView && cellAnomaly?.flag && (
                      <div
                        style={{
                          marginTop: 8,
                          padding: "6px 10px",
                          background: "rgba(255, 59, 59, 0.08)",
                          border: "1px solid rgba(255, 59, 59, 0.25)",
                          borderRadius: 4,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                          }}
                        >
                          <span
                            style={{
                              fontSize: "0.6rem",
                              color: "#ff3b3b",
                              letterSpacing: "0.15em",
                              fontWeight: 600,
                            }}
                          >
                            ANOMALY (ALL LAYERS)
                          </span>
                          {cellAnomaly.score != null && (
                            <span
                              style={{
                                fontFamily: "'DM Mono', monospace",
                                fontSize: "0.7rem",
                                color: "#ff3b3b",
                              }}
                            >
                              Score {cellAnomaly.score.toFixed(2)}
                            </span>
                          )}
                        </div>
                        {cellAnomaly.anomaly_type && (
                          <div
                            style={{
                              fontSize: "0.6rem",
                              color: "var(--text-dim)",
                              marginTop: 3,
                            }}
                          >
                            Type: {cellAnomaly.anomaly_type}
                          </div>
                        )}
                      </div>
                    )}
                    <div
                      style={{
                        fontSize: "0.54rem",
                        color: "var(--text-dim)",
                        marginTop: 8,
                        letterSpacing: "0.06em",
                        lineHeight: 1.5,
                      }}
                    >
                      Cell {cell.cell_code || cell.id}
                      {cell.match_type === "nearest"
                        ? ` · ${cell.distance_to_centroid_m} m from click`
                        : ""}
                      {cellMetrics.basis?.startsWith("live")
                        ? " · values from the current map layers"
                        : ""}
                    </div>
                  </div>
                </div>
              )}

              {/* Municipality (context) */}
              {municipality && (
                <div style={{ marginBottom: 14 }}>
                  <SpatialLevelHeader
                    level="3"
                    label="Municipality"
                    sublabel="Administrative boundary · context only"
                    accent="#00b4d8"
                  />
                  <div
                    style={{
                      ...boxStyle("0, 180, 216", "#00b4d8"),
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <div
                      style={{
                        fontFamily: "'Syne', sans-serif",
                        fontSize: "0.92rem",
                        fontWeight: 600,
                        color: "rgba(255,255,255,0.92)",
                      }}
                    >
                      {municipality.name}
                    </div>
                    <div
                      style={{
                        padding: "3px 8px",
                        fontSize: "0.55rem",
                        letterSpacing: "0.15em",
                        color: "#00b4d8",
                        background: "rgba(0, 180, 216, 0.12)",
                        border: "1px solid rgba(0, 180, 216, 0.25)",
                        borderRadius: 3,
                      }}
                    >
                      ADMIN
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Deep Analysis ─────────────────────────────────────────── */}
            <div
              style={{
                padding: "12px 18px",
                borderTop: "1px solid rgba(0,229,255,0.1)",
                flexShrink: 0,
              }}
            >
              <button
                onClick={onDeepAnalysis}
                style={{
                  width: "100%",
                  padding: "10px 0",
                  background: "transparent",
                  border: "1px solid rgba(0,229,255,0.28)",
                  borderRadius: 6,
                  color: "rgba(0,229,255,0.8)",
                  fontFamily: "'DM Mono', monospace",
                  fontSize: "0.62rem",
                  letterSpacing: "0.18em",
                  cursor: "pointer",
                  textTransform: "uppercase",
                  transition: "all 0.22s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(0,229,255,0.08)";
                  e.currentTarget.style.boxShadow =
                    "0 0 20px rgba(0,229,255,0.18)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.boxShadow = "none";
                }}
              >
                ▶ View Deep Analysis
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

// ── Small helpers ──────────────────────────────────────────────────────────

function boxStyle(rgb, accent) {
  return {
    padding: "10px 12px",
    background: `rgba(${rgb}, 0.04)`,
    border: `1px solid rgba(${rgb}, 0.15)`,
    borderLeft: `3px solid ${accent}`,
    borderRadius: 4,
  };
}

function CloseButton({ onClick }) {
  return (
    <button
      onClick={onClick}
      aria-label="Close"
      style={{
        position: "absolute",
        top: 14,
        right: 14,
        background: "none",
        border: "1px solid rgba(0,229,255,0.18)",
        borderRadius: 4,
        color: "var(--text-dim)",
        width: 24,
        height: 24,
        cursor: "pointer",
        fontSize: "11px",
        fontFamily: "inherit",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "all 0.2s ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = "var(--cyan)";
        e.currentTarget.style.borderColor = "rgba(0,229,255,0.4)";
        e.currentTarget.style.boxShadow = "0 0 8px rgba(0,229,255,0.2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = "var(--text-dim)";
        e.currentTarget.style.borderColor = "rgba(0,229,255,0.18)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      ✕
    </button>
  );
}

function SpatialLevelHeader({ level, label, sublabel, accent }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 8,
      }}
    >
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: "50%",
          border: `1.5px solid ${accent}`,
          background: `${accent}15`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "'DM Mono', monospace",
          fontSize: "0.65rem",
          fontWeight: 700,
          color: accent,
          textShadow: `0 0 8px ${accent}66`,
          flexShrink: 0,
        }}
      >
        {level}
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: "'Syne', sans-serif",
            fontSize: "0.74rem",
            fontWeight: 600,
            letterSpacing: "0.12em",
            color: "rgba(255,255,255,0.88)",
            textTransform: "uppercase",
          }}
        >
          {label}
        </div>
        {sublabel && (
          <div
            style={{
              fontSize: "0.52rem",
              letterSpacing: "0.08em",
              color: "var(--text-dim)",
              marginTop: 1,
            }}
          >
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  unit = "",
  color = "rgba(255,255,255,0.88)",
  nodata = false,
}) {
  const displayColor = nodata ? "rgba(255,255,255,0.32)" : color;
  const isLongMsg = typeof value === "string" && value.length > 12;
  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: "0.5rem",
          letterSpacing: "0.14em",
          color: "var(--text-dim)",
          textTransform: "uppercase",
          marginBottom: 3,
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: isLongMsg ? "flex-start" : "baseline",
          gap: 3,
          flexWrap: isLongMsg ? "wrap" : "nowrap",
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: isLongMsg ? "0.66rem" : "0.88rem",
            fontWeight: 500,
            color: displayColor,
            textShadow: nodata ? "none" : `0 0 8px ${color}44`,
            opacity: nodata ? 0.6 : 1,
            lineHeight: isLongMsg ? 1.45 : 1,
            wordBreak: isLongMsg ? "break-word" : "normal",
            minWidth: 0,
          }}
        >
          {value}
        </span>
        {unit && (
          <span
            style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: "0.6rem",
              fontWeight: 400,
              color: displayColor,
              opacity: nodata ? 0.5 : 0.7,
              flexShrink: 0,
            }}
          >
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function Divider() {
  return (
    <div
      style={{
        height: 1,
        margin: "14px 0",
        background:
          "linear-gradient(to right, rgba(0,229,255,0.12), transparent)",
      }}
    />
  );
}

function SectionLabel({ children }) {
  return (
    <div
      style={{
        fontSize: "0.55rem",
        letterSpacing: "0.2em",
        color: "var(--text-dim)",
        textTransform: "uppercase",
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

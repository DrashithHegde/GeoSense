import { getAqiCpcbBand, getLstBand, getNdviBand, getWaterHealthBand, getSeverityColor, getSeverityLabel, getZoneMetrics, getMetricDisplay, normalizeMetric } from "../../utils/helpers";
import TrendSparkline from "../ui/TrendSparkline";
import RootCauseBar from "../ui/RootCauseBar";

const LAYER_PRIORITY = ["aqi", "ndvi", "water_health", "lst"];
const COMPOSITE_ACCENT_COLOR = "#b45309";

const LAYER_META = {
  aqi: { icon: "○", label: "AQI", color: "#ff8c00" },
  ndvi: { icon: "◇", label: "NDVI", color: "#1dd1a1" },
  water_health: { icon: "◈", label: "Water Health", color: "#00b4d8" },
  lst: { icon: "▣", label: "LST", color: "#ff5f57" },
};

function resolveActiveLayerId(activeLayers) {
  if (!activeLayers) return "aqi";
  if (activeLayers.all) return "all";

  const selected = LAYER_PRIORITY.filter((layerId) => activeLayers[layerId]);
  if (selected.length > 1) return "all";
  if (selected.length === 1) return selected[0];

  return "aqi";
}

// ─────────────────────────────────────────────────────────────────────────────
// InsightPanel
// Slides in from the right when a zone is clicked.
// Width: 420px | Transition: 400ms cubic-bezier spring
// Root cause analysis panel
// ─────────────────────────────────────────────────────────────────────────────

export default function InsightPanel({ zone, pointAnalysis, cityLabel, explanationData, activeLayers, isOpen, onClose, onDeepAnalysis }) {
  const metrics = zone ? getZoneMetrics(zone) : null;
  const activeLayerId = resolveActiveLayerId(activeLayers);
  const isCompositeView = activeLayerId === "all";
  const activeLayerMeta = LAYER_META[activeLayerId] || LAYER_META.aqi;

  // Extract point analysis hierarchy — prefer explicit prop, fall back to attached data
  const pixel = pointAnalysis?.pixel || zone?.pointAnalysis?.pixel || null;
  const cell = pointAnalysis?.cell || zone?.pointAnalysis?.cell || null;
  const municipality = pointAnalysis?.municipality || zone?.pointAnalysis?.municipality || null;

  // Convenience: pixel-level values (exact satellite pixel)
  const pixelNdvi = pixel?.ndvi && !pixel.ndvi.nodata ? pixel.ndvi.value : null;
  const pixelLst = pixel?.lst && !pixel.lst.nodata ? pixel.lst.value_c : null;
  const pixelAqi = pixel?.aqi && !pixel.aqi.nodata ? pixel.aqi.value : null;
  const pixelWaterHealth = pixel?.water_health && !pixel.water_health.nodata ? pixel.water_health.value : null;

  // Convenience: cell-level aggregated values (300m grid)
  const cellMetrics = cell?.metrics || {};
  const cellNdvi = cellMetrics.ndvi ?? null;
  const cellLst = cellMetrics.lst ?? null;
  const cellAqi = cellMetrics.aqi ?? null;
  const cellWater = cellMetrics.water_health_score ?? null;
  const cellAnomaly = cell?.anomaly || null;

  // Extract unit for LST display
  let panelValue, panelUnit = "";
  if (isCompositeView) {
    panelValue = zone?.composite?.score == null ? "N/A" : zone.composite.score.toFixed(1);
  } else if (activeLayerId === "water_health") {
    panelValue = metrics?.water_health_score == null ? "N/A" : `${(metrics.water_health_score * 100).toFixed(0)}%`;
  } else if (activeLayerId === "lst") {
    panelValue = metrics?.lst !== null && metrics?.lst !== undefined ? metrics.lst.toFixed(1) : "N/A";
    panelUnit = metrics?.lst !== null && metrics?.lst !== undefined ? "°C" : "";
  } else {
    panelValue = getMetricDisplay(activeLayerId, metrics);
  }

  const panelLabel = isCompositeView
    ? "Composite Risk Score (Cell-Level)"
    : activeLayerId === "lst" && pixelLst !== null
      ? "Cell Mean LST (see Pixel below for exact value)"
      : `${activeLayerMeta.label} — Analytical Cell Mean`;
  const panelValueColor = isCompositeView ? COMPOSITE_ACCENT_COLOR : activeLayerMeta.color;
  const stressValue = isCompositeView
    ? zone?.composite?.score ?? null
    : normalizeMetric(activeLayerId, metrics);
  const stressLabel = isCompositeView ? "Stress Index" : `${activeLayerMeta.label} Intensity`;
  const breakdownLabel = isCompositeView
    ? "Root Cause Breakdown"
    : `${activeLayerMeta.label} Breakdown`;
  const trendLabel = isCompositeView
    ? "14-Day Trend"
    : `14-Day ${activeLayerMeta.label} Trend`;
  const severityScore = isCompositeView ? (zone?.severity ?? 0) : stressValue;
  const severityLabel = (() => {
    if (activeLayerId === "aqi") return getAqiCpcbBand(metrics?.aqi);
    if (activeLayerId === "ndvi") return getNdviBand(metrics?.ndvi);
    if (activeLayerId === "water_health") return getWaterHealthBand(metrics?.water_health_score);
    if (activeLayerId === "lst") return getLstBand(metrics?.lst);
    return getSeverityLabel(severityScore);
  })();
  const severityColor = getSeverityColor(severityScore);
  const severityScopeLabel = isCompositeView ? "Composite" : activeLayerId === "aqi" ? "CPCB AQI" : activeLayerMeta.label;
  const zoneDisplayName = cityLabel ? `${zone?.name}, ${cityLabel}` : zone?.name;

  // Real backend classification if available
  const classification = explanationData?.classification
    ? explanationData.classification.toUpperCase()
    : cellAnomaly?.flag
      ? "ANOMALY"
      : zone?.is_anomaly
        ? "ANOMALY"
        : "INLIER";

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
        transition: "transform 0.4s cubic-bezier(0.22,1,0.36,1), opacity 0.4s ease",
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
            {/* ── Header ─────────────────────────────────────────────────── */}
            <div
              style={{
                padding: "16px 18px",
                borderBottom: "1px solid rgba(0,229,255,0.1)",
                position: "relative",
                flexShrink: 0,
              }}
            >
              {/* Close button */}
              <button
                onClick={onClose}
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

              <div
                style={{
                  fontSize: "0.52rem",
                  letterSpacing: "0.2em",
                  color: classification === "ANOMALY" ? "rgba(255,59,59,0.7)" : "rgba(0,229,255,0.5)",
                  textTransform: "uppercase",
                  marginBottom: 6,
                  marginTop: 6,
                }}
              >
                {classification === "ANOMALY" ? "ANOMALY DETECTED" : "ROOT CAUSE ANALYSIS"}
              </div>

              <div
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontSize: "0.95rem",
                  fontWeight: 600,
                  color: "rgba(255,255,255,0.9)",
                  letterSpacing: "0.04em",
                  lineHeight: 1.45,
                  paddingBottom: 2,
                  paddingRight: 28,
                }}
              >
                {zoneDisplayName}
              </div>

              <div
                style={{
                  marginTop: 5,
                  fontSize: "0.55rem",
                  color: "var(--text-dim)",
                  letterSpacing: "0.1em",
                }}
              >
                SEVERITY ({severityScopeLabel.toUpperCase()}):{" "}
                <span style={{ color: severityColor }}>
                  {severityLabel}
                </span>
                {"  ·  "}
                {municipality?.name
                  ? `Within ${municipality.name}`
                  : zone.coords ? `${zone.coords[1].toFixed(4)}°N ${zone.coords[0].toFixed(4)}°E`
                    : ""}
              </div>
            </div>

            {/* ── Body ───────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px 18px" }}>

              {/* ══════════════════════════════════════════════
                 SPATIAL HIERARCHY — THREE DISTINCT LEVELS
                 ══════════════════════════════════════════════ */}

              {(pixel || cell || municipality) && (
                <div style={{ marginBottom: 14 }}>
                  <SectionLabel>▣  CLICKED LOCATION</SectionLabel>
                  <div style={{
                    padding: "10px 12px",
                    background: "rgba(0,229,255,0.04)",
                    border: "1px solid rgba(0,229,255,0.12)",
                    borderRadius: 6,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.85rem", color: "rgba(255,255,255,0.9)" }}>
                        {(pixel?.latitude ?? zone?.coords?.[1]) != null
                          ? `${(pixel?.latitude ?? zone?.coords?.[1]).toFixed(5)}°N`
                          : "—"}
                      </span>
                      <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.85rem", color: "rgba(255,255,255,0.9)" }}>
                        {(pixel?.longitude ?? zone?.coords?.[0]) != null
                          ? `${(pixel?.longitude ?? zone?.coords?.[0]).toFixed(5)}°E`
                          : "—"}
                      </span>
                    </div>
                    {cell?.resolution_m && (
                      <div style={{ fontSize: "0.56rem", color: "var(--text-dim)", marginTop: 6, letterSpacing: "0.1em" }}>
                        HIERARCHY: 10m Sentinel-2 pixel  →  {cell.resolution_m}m analytical cell  →  Municipality boundary
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── 1. PIXEL LEVEL (exact satellite pixel) */}
              {(pixelNdvi != null || pixelLst != null || pixelAqi != null || pixelWaterHealth != null || pixel) && (
                <div style={{ marginBottom: 14 }}>
                  <SpatialLevelHeader
                    level="1"
                    label="PIXEL"
                    sublabel="Exact satellite pixel · scientific source"
                    accent="#ff5f57"
                  />
                  <div style={{
                    padding: "10px 12px",
                    background: "rgba(255, 95, 87, 0.04)",
                    border: "1px solid rgba(255, 95, 87, 0.15)",
                    borderLeft: "3px solid #ff5f57",
                    borderRadius: 4,
                  }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
                      <MetricRow
                        label="NDVI"
                        value={pixelNdvi != null
                          ? pixelNdvi.toFixed(3)
                          : (pixel?.ndvi?.nodata ? "No valid NDVI observation at this location." : "N/A")}
                        unit=""
                        color="#1dd1a1"
                        nodata={pixel?.ndvi?.nodata}
                      />
                      <MetricRow
                        label="LST"
                        value={pixelLst != null ? pixelLst.toFixed(1) : (pixel?.lst?.nodata ? "NoData" : "N/A")}
                        unit="°C"
                        color="#ff5f57"
                        nodata={pixel?.lst?.nodata}
                      />
                      <MetricRow
                        label="AQI"
                        value={pixelAqi != null ? String(pixelAqi) : (pixel?.aqi?.nodata ? "NoData" : "N/A")}
                        unit=""
                        color="#ff8c00"
                        nodata={pixel?.aqi?.nodata}
                      />
                      <MetricRow
                        label="Water Health"
                        value={pixelWaterHealth != null
                          ? `${(pixelWaterHealth * 100).toFixed(0)}%`
                          : (pixel?.water_health?.nodata ? "No valid water pixel at this location." : "N/A")}
                        unit=""
                        color="#00b4d8"
                        nodata={pixel?.water_health?.nodata}
                      />
                    </div>
                    {(pixel?.ndvi?.source || pixel?.lst?.source) && (
                      <div style={{ fontSize: "0.54rem", color: "var(--text-dim)", marginTop: 8, letterSpacing: "0.08em", lineHeight: 1.5 }}>
                        Source: {pixel?.ndvi?.source || pixel?.lst?.source}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── 2. CELL LEVEL (300m analytical grid) */}
              {cell && (
                <div style={{ marginBottom: 14 }}>
                  <SpatialLevelHeader
                    level="2"
                    label="LOCAL ANALYTICAL CELL"
                    sublabel={`${cell.resolution_m || 300}m grid · zonal aggregates`}
                    accent="#1dd1a1"
                  />
                  <div style={{
                    padding: "10px 12px",
                    background: "rgba(29, 209, 161, 0.04)",
                    border: "1px solid rgba(29, 209, 161, 0.15)",
                    borderLeft: "3px solid #1dd1a1",
                    borderRadius: 4,
                  }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px", marginBottom: cellAnomaly?.flag ? 10 : 0 }}>
                      <MetricRow label="AQI" value={cellAqi != null ? String(cellAqi) : "N/A"} color="#ff8c00" />
                      <MetricRow label="NDVI" value={cellNdvi != null ? cellNdvi.toFixed(2) : "N/A"} color="#1dd1a1" />
                      <MetricRow label="LST" value={cellLst != null ? cellLst.toFixed(1) : "N/A"} unit="°C" color="#ff5f57" />
                      <MetricRow label="Water" value={cellWater != null ? `${(cellWater * 100).toFixed(0)}%` : "N/A"} color="#00b4d8" />
                    </div>
                    {cellAnomaly?.flag && (
                      <div style={{
                        marginTop: 8,
                        padding: "6px 10px",
                        background: "rgba(255, 59, 59, 0.08)",
                        border: "1px solid rgba(255, 59, 59, 0.25)",
                        borderRadius: 4,
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span style={{ fontSize: "0.6rem", color: "#ff3b3b", letterSpacing: "0.15em", fontWeight: 600 }}>
                            ANOMALY DETECTED
                          </span>
                          {cellAnomaly.score != null && (
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.7rem", color: "#ff3b3b" }}>
                              Score {cellAnomaly.score.toFixed(2)}
                            </span>
                          )}
                        </div>
                        {cellAnomaly.anomaly_type && (
                          <div style={{ fontSize: "0.6rem", color: "var(--text-dim)", marginTop: 3 }}>
                            Type: {cellAnomaly.anomaly_type}
                          </div>
                        )}
                      </div>
                    )}
                    {cell.centroid && (
                      <div style={{ fontSize: "0.54rem", color: "var(--text-dim)", marginTop: 8, letterSpacing: "0.08em" }}>
                        Cell ID: {cell.id}  ·  Centroid: {cell.centroid.latitude.toFixed(4)}°N, {cell.centroid.longitude.toFixed(4)}°E
                        {cell.match_type === "nearest" ? `  ·  ${cell.distance_to_centroid_m}m from click` : ""}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── 3. MUNICIPALITY LEVEL (admin boundary) */}
              {municipality && (
                <div style={{ marginBottom: 14 }}>
                  <SpatialLevelHeader
                    level="3"
                    label="MUNICIPALITY"
                    sublabel="Administrative boundary · context only"
                    accent="#00b4d8"
                  />
                  <div style={{
                    padding: "10px 12px",
                    background: "rgba(0, 180, 216, 0.04)",
                    border: "1px solid rgba(0, 180, 216, 0.15)",
                    borderLeft: "3px solid #00b4d8",
                    borderRadius: 4,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}>
                    <div>
                      <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "0.95rem", fontWeight: 600, color: "rgba(255,255,255,0.92)" }}>
                        {municipality.name}
                      </div>
                      <div style={{ fontSize: "0.56rem", color: "var(--text-dim)", marginTop: 2, letterSpacing: "0.08em" }}>
                        {municipality.source || "Administrative containment"}
                      </div>
                    </div>
                    <div style={{
                      padding: "3px 8px",
                      fontSize: "0.55rem",
                      letterSpacing: "0.15em",
                      color: "#00b4d8",
                      background: "rgba(0, 180, 216, 0.12)",
                      border: "1px solid rgba(0, 180, 216, 0.25)",
                      borderRadius: 3,
                    }}>
                      ADMIN
                    </div>
                  </div>
                </div>
              )}

              {/* ── Divider after hierarchy sections */}
              {(pixel || cell || municipality) && <Divider />}

              {/* Active score */}
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  marginBottom: 14,
                }}
              >
                <span
                  style={{
                    fontSize: "0.58rem",
                    color: "var(--text-dim)",
                    letterSpacing: "0.18em",
                    textTransform: "uppercase",
                  }}
                >
                  {panelLabel}
                </span>
                <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                  <span
                    style={{
                      fontFamily: "'DM Mono', monospace",
                      fontSize: "2.2rem",
                      fontWeight: 600,
                      color: panelValueColor,
                      textShadow: `0 0 24px ${panelValueColor}66`,
                      lineHeight: 1,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    {panelValue}
                  </span>
                  {panelUnit && (
                    <span
                      style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: "0.9rem",
                        fontWeight: 600,
                        color: panelValueColor,
                        textShadow: `0 0 24px ${panelValueColor}66`,
                        lineHeight: 1,
                        letterSpacing: "-0.02em",
                      }}
                    >
                      {panelUnit}
                    </span>
                  )}
                </div>
              </div>

              {/* Stress index bar */}
              <div style={{ marginBottom: 18 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "0.58rem",
                    color: "var(--text-dim)",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom: 6,
                  }}
                >
                  <span>{stressLabel}</span>
                  <span style={{ color: panelValueColor, fontFamily: "'DM Mono', monospace", fontWeight: 400, fontSize: "0.58rem" }}>{stressValue == null ? "N/A" : `${Math.round(stressValue)}%`}</span>
                </div>
                <div
                  style={{
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
                      background: panelValueColor,
                      boxShadow: `0 0 10px ${panelValueColor}88`,
                      borderRadius: 2,
                      transition: "width 1s cubic-bezier(0.22,1,0.36,1)",
                    }}
                  />
                </div>
              </div>

              {/* Divider */}
              <Divider />

              {/* Root cause breakdown */}
              {isCompositeView && (
                <>
                  <SectionLabel>{breakdownLabel}</SectionLabel>
                  <RootCauseBar
                    icon="○"
                    label="AQI"
                    value={metrics.aqi}
                    normalizedValue={zone.composite?.contributions?.aqi == null ? null : zone.composite.contributions.aqi * 100}
                    displayValue={getMetricDisplay("aqi", metrics)}
                    color="#ff8c00"
                  />
                  <RootCauseBar
                    icon="◇"
                    label="NDVI"
                    value={metrics.ndvi}
                    normalizedValue={zone.composite?.contributions?.ndvi == null ? null : zone.composite.contributions.ndvi * 100}
                    displayValue={getMetricDisplay("ndvi", metrics)}
                    color="#1dd1a1"
                  />
                  <RootCauseBar
                    icon="◈"
                    label="Water"
                    value={metrics.water_health_score}
                    normalizedValue={zone.composite?.contributions?.water_health == null ? null : zone.composite.contributions.water_health * 100}
                    displayValue={metrics.water_health_score == null ? "N/A" : `${(metrics.water_health_score * 100).toFixed(0)}%`}
                    color="#00b4d8"
                  />
                  <RootCauseBar
                    icon="▣"
                    label="LST"
                    value={metrics.lst}
                    normalizedValue={zone.composite?.contributions?.lst == null ? null : zone.composite.contributions.lst * 100}
                    displayValue={getMetricDisplay("lst", metrics)}
                    color="#ff5f57"
                  />
                  {/* Divider */}
                  <Divider />
                </>
              )}

              {/* Trend / Explanation */}
              <SectionLabel>Insight Summary</SectionLabel>
              <div
                style={{
                  minHeight: 62,
                  borderLeft: "1px solid rgba(0,229,255,0.14)",
                  marginBottom: 16,
                  paddingLeft: 12,
                  position: "relative",
                  color: "var(--text-dim)",
                  fontSize: "0.75rem",
                  lineHeight: 1.5,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                {explanationData ? (
                  explanationData._unavailable ? (
                    <span style={{ fontStyle: "italic", opacity: 0.7 }}>Temporal data: insufficient history.</span>
                  ) : (
                    explanationData.deterministic_explanation && (
                      <span>
                        {explanationData.deterministic_explanation.split('\n')[0]}
                      </span>
                    )
                  )
                ) : (
                  <span style={{ opacity: 0.5 }}>Loading analysis...</span>
                )}

                {(pixel || cell || municipality) && (
                  <div
                    style={{
                      marginTop: explanationData ? 2 : 0,
                      padding: "8px 10px",
                      background: "rgba(0,229,255,0.03)",
                      border: "1px solid rgba(0,229,255,0.08)",
                      borderRadius: 4,
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                    }}
                  >
                    {(pixelNdvi != null || pixelWaterHealth != null) && (
                      <div>
                        <span style={{ color: "#ff5f57", fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", letterSpacing: "0.12em", fontWeight: 600 }}>PIXEL · </span>
                        <span style={{ color: "rgba(255,255,255,0.78)" }}>
                          At the clicked location, satellite-derived
                          {pixelNdvi != null && <> NDVI is <b style={{ color: "#1dd1a1" }}>{pixelNdvi.toFixed(3)}</b></>}
                          {pixelNdvi != null && pixelWaterHealth != null && <>, </>}
                          {pixelWaterHealth != null && <> Water Health is <b style={{ color: "#00b4d8" }}>{(pixelWaterHealth * 100).toFixed(0)}%</b></>}
                          {pixelLst != null && <> and LST is <b style={{ color: "#ff5f57" }}>{pixelLst.toFixed(1)}°C</b></>}.
                        </span>
                      </div>
                    )}
                    {(cellNdvi != null || cellLst != null || cellAqi != null) && (
                      <div>
                        <span style={{ color: "#1dd1a1", fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", letterSpacing: "0.12em", fontWeight: 600 }}>CELL · </span>
                        <span style={{ color: "rgba(255,255,255,0.78)" }}>
                          Surrounding {cell?.resolution_m || 300}m analytical cell
                          {cellAqi != null && <> — AQI <b style={{ color: "#ff8c00" }}>{cellAqi}</b></>}
                          {cellNdvi != null && <> — NDVI avg <b style={{ color: "#1dd1a1" }}>{cellNdvi.toFixed(2)}</b></>}
                          {cellLst != null && <> — LST avg <b style={{ color: "#ff5f57" }}>{cellLst.toFixed(1)}°C</b></>}.
                        </span>
                      </div>
                    )}
                    {municipality?.name && (
                      <div>
                        <span style={{ color: "#00b4d8", fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", letterSpacing: "0.12em", fontWeight: 600 }}>MUNICIPALITY · </span>
                        <span style={{ color: "rgba(255,255,255,0.78)" }}>
                          Clicked location falls within <b style={{ color: "#00b4d8" }}>{municipality.name}</b>.
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* CTA (for non-composite, scrolls with content) */}
              {!isCompositeView && (
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
                    e.currentTarget.style.boxShadow = "0 0 20px rgba(0,229,255,0.18)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.boxShadow = "none";
                  }}
                >
                  ▶ View Deep Analysis
                </button>
              )}
            </div>

            {/* ── Deep Analysis CTA (Fixed Footer, Only for Composite) ─────── */}
            {isCompositeView && (
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
                    e.currentTarget.style.boxShadow = "0 0 20px rgba(0,229,255,0.18)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.boxShadow = "none";
                  }}
                >
                  ▶ View Deep Analysis
                </button>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

// ── Small helpers ──────────────────────────────────────────────────────────

function SpatialLevelHeader({ level, label, sublabel, accent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
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

function MetricRow({ label, value, unit = "", color = "rgba(255,255,255,0.88)", nodata = false }) {
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
        background: "linear-gradient(to right, rgba(0,229,255,0.12), transparent)",
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

import { getAqiCpcbBand, getLstBand, getNdviBand, getNdwiBand, getSeverityColor, getSeverityLabel, getZoneMetrics, getMetricDisplay, normalizeMetric } from "../../utils/helpers";
import TrendSparkline from "../ui/TrendSparkline";
import RootCauseBar from "../ui/RootCauseBar";

const LAYER_PRIORITY = ["aqi", "ndvi", "ndwi", "lst"];
const COMPOSITE_ACCENT_COLOR = "#b45309";

const LAYER_META = {
  aqi: { icon: "○", label: "AQI", color: "#ff8c00" },
  ndvi: { icon: "◇", label: "NDVI", color: "#1dd1a1" },
  ndwi: { icon: "◈", label: "NDWI", color: "#00b4d8" },
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

export default function InsightPanel({ zone, cityLabel, trendData, activeLayers, isOpen, onClose, onDeepAnalysis }) {
  const metrics = zone ? getZoneMetrics(zone) : null;
  const activeLayerId = resolveActiveLayerId(activeLayers);
  const isCompositeView = activeLayerId === "all";
  const activeLayerMeta = LAYER_META[activeLayerId] || LAYER_META.aqi;
  const panelValue = isCompositeView
    ? zone?.severity.toFixed(1)
    : getMetricDisplay(activeLayerId, metrics);
  const panelLabel = isCompositeView
    ? "Composite Risk Score"
    : `${activeLayerMeta.label} Metric`;
  const panelValueColor = isCompositeView ? COMPOSITE_ACCENT_COLOR : activeLayerMeta.color;
  const stressValue = isCompositeView
    ? zone?.severity
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
    if (activeLayerId === "ndwi") return getNdwiBand(metrics?.ndwi);
    if (activeLayerId === "lst") return getLstBand(metrics?.lst);
    return getSeverityLabel(severityScore);
  })();
  const severityColor = getSeverityColor(severityScore);
  const severityScopeLabel = isCompositeView ? "Composite" : activeLayerId === "aqi" ? "CPCB AQI" : activeLayerMeta.label;
  const zoneDisplayName = cityLabel ? `${zone?.name}, ${cityLabel}` : zone?.name;

  return (
    <div
      style={{
        position: "fixed",
        top: 100,
        right: 16,
        bottom: 120,
        zIndex: 40,
        width: 420,
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
                  color: "rgba(0,229,255,0.5)",
                  textTransform: "uppercase",
                  marginBottom: 6,
                  marginTop: 6,
                }}
              >
                ROOT CAUSE ANALYSIS
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
                {zone.coords[1].toFixed(4)}°N {zone.coords[0].toFixed(4)}°E
              </div>
            </div>

            {/* ── Body ───────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: isCompositeView ? "auto" : "visible", padding: "16px 18px" }}>

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
                <span
                  style={{
                    fontFamily: "'Syne', sans-serif",
                    fontSize: "2.2rem",
                    fontWeight: 700,
                    color: panelValueColor,
                    textShadow: `0 0 24px ${panelValueColor}66`,
                    lineHeight: 1,
                  }}
                >
                  {panelValue}
                </span>
              </div>

              {/* Stress index bar */}
              <div style={{ marginBottom: 18 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "0.56rem",
                    color: "var(--text-dim)",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom: 6,
                  }}
                >
                  <span>{stressLabel}</span>
                  <span style={{ color: panelValueColor }}>{Math.round(stressValue)}%</span>
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
                      width: `${Math.max(0, Math.min(100, stressValue))}%`,
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
              <SectionLabel>{breakdownLabel}</SectionLabel>
              {isCompositeView ? (
                <>
                  <RootCauseBar
                    icon="○"
                    label="AQI"
                    value={metrics.aqi}
                    normalizedValue={normalizeMetric("aqi", metrics)}
                    displayValue={getMetricDisplay("aqi", metrics)}
                    color="#ff8c00"
                  />
                  <RootCauseBar
                    icon="◇"
                    label="NDVI"
                    value={metrics.ndvi}
                    normalizedValue={normalizeMetric("ndvi", metrics)}
                    displayValue={getMetricDisplay("ndvi", metrics)}
                    color="#1dd1a1"
                  />
                  <RootCauseBar
                    icon="◈"
                    label="NDWI"
                    value={metrics.ndwi}
                    normalizedValue={normalizeMetric("ndwi", metrics)}
                    displayValue={getMetricDisplay("ndwi", metrics)}
                    color="#00b4d8"
                  />
                  <RootCauseBar
                    icon="▣"
                    label="LST"
                    value={metrics.lst}
                    normalizedValue={normalizeMetric("lst", metrics)}
                    displayValue={getMetricDisplay("lst", metrics)}
                    color="#ff5f57"
                  />
                </>
              ) : (
                <RootCauseBar
                  icon={activeLayerMeta.icon}
                  label={activeLayerMeta.label}
                  value={metrics[activeLayerId]}
                  normalizedValue={normalizeMetric(activeLayerId, metrics)}
                  displayValue={getMetricDisplay(activeLayerId, metrics)}
                  color={activeLayerMeta.color}
                />
              )}

              {/* Divider */}
              <Divider />

              {/* Trend */}
              <SectionLabel>{trendLabel}</SectionLabel>
              <div
                style={{
                  height: 62,
                  borderLeft: "1px solid rgba(0,229,255,0.14)",
                  borderBottom: "1px solid rgba(0,229,255,0.14)",
                  marginBottom: 4,
                  position: "relative",
                }}
              >
                <TrendSparkline data={trendData} color={panelValueColor} />
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "0.5rem",
                  color: "rgba(200,214,229,0.25)",
                  letterSpacing: "0.1em",
                  marginBottom: 16,
                }}
              >
                <span>14D AGO</span>
                <span>TREND</span>
                <span>NOW</span>
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

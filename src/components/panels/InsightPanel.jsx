import { getSeverityColor } from "../../utils/helpers";
import TrendSparkline        from "../ui/TrendSparkline";
import RootCauseBar          from "../ui/RootCauseBar";

// ─────────────────────────────────────────────────────────────────────────────
// InsightPanel
// Slides in from the right when a zone is clicked.
// Width: 380px | Transition: 400ms cubic-bezier spring
// ─────────────────────────────────────────────────────────────────────────────

export default function InsightPanel({ zone, trendData, isOpen, onClose }) {
  const color = zone ? getSeverityColor(zone.severity) : "#1dd1a1";

  return (
    <div
      style={{
        position:   "fixed",
        top:        72,
        right:      0,
        bottom:     80,
        zIndex:     40,
        width:      380,
        transform:  isOpen ? "translateX(0)" : "translateX(100%)",
        opacity:    isOpen ? 1 : 0,
        transition: "transform 0.4s cubic-bezier(0.22,1,0.36,1), opacity 0.4s ease",
        display:    "flex",
        flexDirection:"column",
      }}
    >
      <div
        className="glass"
        style={{
          borderRadius: "12px 0 0 12px",
          borderRight:  "none",
          flex:         1,
          display:      "flex",
          flexDirection:"column",
          overflow:     "hidden",
        }}
      >
        {zone && (
          <>
            {/* ── Header ─────────────────────────────────────────────────── */}
            <div
              style={{
                padding:      "16px 18px",
                borderBottom: "1px solid rgba(0,229,255,0.1)",
                position:     "relative",
                flexShrink:   0,
              }}
            >
              {/* Close button */}
              <button
                onClick={onClose}
                style={{
                  position:      "absolute",
                  top:           14,
                  right:         14,
                  background:    "none",
                  border:        "1px solid rgba(0,229,255,0.18)",
                  borderRadius:  4,
                  color:         "var(--text-dim)",
                  width:         24,
                  height:        24,
                  cursor:        "pointer",
                  fontSize:      "11px",
                  fontFamily:    "inherit",
                  display:       "flex",
                  alignItems:    "center",
                  justifyContent:"center",
                  transition:    "all 0.2s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color       = "var(--cyan)";
                  e.currentTarget.style.borderColor = "rgba(0,229,255,0.4)";
                  e.currentTarget.style.boxShadow   = "0 0 8px rgba(0,229,255,0.2)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color       = "var(--text-dim)";
                  e.currentTarget.style.borderColor = "rgba(0,229,255,0.18)";
                  e.currentTarget.style.boxShadow   = "none";
                }}
              >
                ✕
              </button>

              <div
                style={{
                  fontSize:     "0.52rem",
                  letterSpacing:"0.2em",
                  color:        "rgba(0,229,255,0.5)",
                  textTransform:"uppercase",
                  marginBottom: 6,
                }}
              >
                ENV-ANOMALY DETECTED
              </div>

              <div
                style={{
                  fontFamily:   "'Syne', sans-serif",
                  fontSize:     "0.95rem",
                  fontWeight:   600,
                  color:        "rgba(255,255,255,0.9)",
                  letterSpacing:"0.04em",
                  lineHeight:   1.3,
                  paddingRight: 28,
                }}
              >
                {zone.name}
              </div>

              <div
                style={{
                  marginTop:    5,
                  fontSize:     "0.55rem",
                  color:        "var(--text-dim)",
                  letterSpacing:"0.1em",
                }}
              >
                SEVERITY:{" "}
                <span style={{ color }}>
                  {zone.type.toUpperCase()}
                </span>
                {"  ·  "}
                {zone.coords[1].toFixed(4)}°N {zone.coords[0].toFixed(4)}°E
              </div>
            </div>

            {/* ── Body ───────────────────────────────────────────────────── */}
            <div style={{ flex:1, overflowY:"auto", padding:"16px 18px" }}>

              {/* Risk score */}
              <div
                style={{
                  display:       "flex",
                  alignItems:    "baseline",
                  justifyContent:"space-between",
                  marginBottom:  14,
                }}
              >
                <span
                  style={{
                    fontSize:     "0.58rem",
                    color:        "var(--text-dim)",
                    letterSpacing:"0.18em",
                    textTransform:"uppercase",
                  }}
                >
                  Risk Score
                </span>
                <span
                  style={{
                    fontFamily: "'Syne', sans-serif",
                    fontSize:   "2.2rem",
                    fontWeight: 700,
                    color,
                    textShadow: `0 0 24px ${color}66`,
                    lineHeight: 1,
                  }}
                >
                  {zone.severity.toFixed(1)}
                </span>
              </div>

              {/* Stress index bar */}
              <div style={{ marginBottom:18 }}>
                <div
                  style={{
                    display:       "flex",
                    justifyContent:"space-between",
                    fontSize:      "0.56rem",
                    color:         "var(--text-dim)",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom:  6,
                  }}
                >
                  <span>Stress Index</span>
                  <span style={{ color }}>{zone.severity}%</span>
                </div>
                <div
                  style={{
                    height:     3,
                    background: "rgba(255,255,255,0.06)",
                    borderRadius:2,
                    overflow:   "hidden",
                  }}
                >
                  <div
                    style={{
                      height:    "100%",
                      width:     `${zone.severity}%`,
                      background:color,
                      boxShadow: `0 0 10px ${color}88`,
                      borderRadius:2,
                      transition: "width 1s cubic-bezier(0.22,1,0.36,1)",
                    }}
                  />
                </div>
              </div>

              {/* Divider */}
              <Divider />

              {/* Root cause breakdown */}
              <SectionLabel>Root Cause Breakdown</SectionLabel>
              <RootCauseBar icon="○" label="Air"   value={zone.air}   color="#ff8c00" />
              <RootCauseBar icon="◈" label="Water" value={zone.water} color="#00b4d8" />
              <RootCauseBar icon="◇" label="Land"  value={zone.land}  color="#1dd1a1" />

              {/* Divider */}
              <Divider />

              {/* Trend */}
              <SectionLabel>14-Day Trend</SectionLabel>
              <div
                style={{
                  height:      62,
                  borderLeft:  "1px solid rgba(0,229,255,0.14)",
                  borderBottom:"1px solid rgba(0,229,255,0.14)",
                  marginBottom:4,
                  position:    "relative",
                }}
              >
                <TrendSparkline data={trendData} color={color} />
              </div>
              <div
                style={{
                  display:       "flex",
                  justifyContent:"space-between",
                  fontSize:      "0.5rem",
                  color:         "rgba(200,214,229,0.25)",
                  letterSpacing: "0.1em",
                  marginBottom:  16,
                }}
              >
                <span>14D AGO</span>
                <span>TREND</span>
                <span>NOW</span>
              </div>

              {/* CTA */}
              <button
                style={{
                  width:        "100%",
                  padding:      "10px 0",
                  background:   "transparent",
                  border:       "1px solid rgba(0,229,255,0.28)",
                  borderRadius: 6,
                  color:        "rgba(0,229,255,0.8)",
                  fontFamily:   "'DM Mono', monospace",
                  fontSize:     "0.62rem",
                  letterSpacing:"0.18em",
                  cursor:       "pointer",
                  textTransform:"uppercase",
                  transition:   "all 0.22s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(0,229,255,0.08)";
                  e.currentTarget.style.boxShadow  = "0 0 20px rgba(0,229,255,0.18)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.boxShadow  = "none";
                }}
              >
                ▶ View Deep Analysis
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Small helpers ──────────────────────────────────────────────────────────

function Divider() {
  return (
    <div
      style={{
        height:     1,
        margin:     "14px 0",
        background: "linear-gradient(to right, rgba(0,229,255,0.12), transparent)",
      }}
    />
  );
}

function SectionLabel({ children }) {
  return (
    <div
      style={{
        fontSize:     "0.55rem",
        letterSpacing:"0.2em",
        color:        "var(--text-dim)",
        textTransform:"uppercase",
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

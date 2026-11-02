import { CITY_CONFIG } from "../../constants/cities";

// ─────────────────────────────────────────────────────────────────────────────
// StatusBar
// Thin system-status strip pinned to the very bottom of the viewport
// ─────────────────────────────────────────────────────────────────────────────

export default function StatusBar({ activeCity, recTime }) {
  return (
    <div
      style={{
        position:      "fixed",
        bottom:        0,
        left:          0,
        right:         0,
        height:        22,
        zIndex:        50,
        background:    "rgba(4,7,11,0.78)",
        borderTop:     "1px solid rgba(0,229,255,0.07)",
        backdropFilter:"blur(10px)",
        display:       "flex",
        alignItems:    "center",
        justifyContent:"space-between",
        padding:       "0 18px",
        fontFamily:    "'DM Mono', monospace",
        fontSize:      "0.52rem",
        letterSpacing: "0.12em",
        color:         "rgba(200,214,229,0.32)",
      }}
    >
      {/* Left — system state */}
      <div style={{ display:"flex", alignItems:"center", gap:7 }}>
        <div
          className="status-pulse"
          style={{
            width:      5,
            height:     5,
            borderRadius:"50%",
            background: "#1dd1a1",
            boxShadow:  "0 0 6px #1dd1a1",
            flexShrink: 0,
          }}
        />
        SYSTEM NOMINAL // ANOMALY DETECTION ACTIVE
      </div>

      {/* Centre — current scope */}
      <div>
        {activeCity
          ? `SCANNING: ${CITY_CONFIG[activeCity]?.label.toUpperCase()}`
          : "INDIA NATIONAL GRID"}
      </div>

      {/* Right — telemetry */}
      <div>
        VIS:382 · SRC:91 · DENS:0.74 · {recTime}
      </div>
    </div>
  );
}

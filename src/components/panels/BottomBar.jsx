import { CITY_CONFIG } from "../../constants/cities";

// ─────────────────────────────────────────────────────────────────────────────
// SeverityLegend
// Horizontal glowing gradient bar with impact labels
// ─────────────────────────────────────────────────────────────────────────────

function SeverityLegend() {
  return (
    <div
      className="glass-sharp"
      style={{
        maxWidth:     560,
        margin:       "0 auto 10px",
        padding:      "8px 18px 10px",
      }}
    >
      <div className="severity-gradient-bar" style={{ marginBottom:5 }} />
      <div
        style={{
          display:       "flex",
          justifyContent:"space-between",
          fontSize:      "0.52rem",
          letterSpacing: "0.12em",
          color:         "var(--text-dim)",
          textTransform: "uppercase",
        }}
      >
        <span style={{ color:"#1dd1a1" }}>● Low Impact</span>
        <span>Moderate</span>
        <span>Severe</span>
        <span style={{ color:"#ff3b3b" }}>● Critical</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CitySelector
// Row of pill buttons for selecting the active city
// ─────────────────────────────────────────────────────────────────────────────

function CitySelector({ activeCity, onSelect }) {
  return (
    <div
      style={{
        display:       "flex",
        alignItems:    "center",
        justifyContent:"center",
        gap:           6,
      }}
    >
      {Object.values(CITY_CONFIG).map((city) => {
        const isActive = activeCity === city.id;

        return (
          <button
            key={city.id}
            onClick={() => onSelect(city.id)}
            style={{
              padding:       "5px 18px",
              background:    isActive
                ? "rgba(0,229,255,0.1)"
                : "rgba(11,15,20,0.72)",
              backdropFilter:"blur(16px)",
              border:        isActive
                ? "1px solid rgba(0,229,255,0.42)"
                : "1px solid rgba(0,229,255,0.12)",
              borderRadius:  4,
              color:         isActive
                ? "rgba(0,229,255,0.9)"
                : "rgba(200,214,229,0.45)",
              fontFamily:    "'DM Mono', monospace",
              fontSize:      "0.62rem",
              letterSpacing: "0.14em",
              cursor:        "pointer",
              textTransform: "uppercase",
              boxShadow:     isActive
                ? "0 0 18px rgba(0,229,255,0.18), inset 0 0 8px rgba(0,229,255,0.06)"
                : "none",
              transition:    "all 0.25s ease",
              display:       "flex",
              alignItems:    "center",
              gap:           6,
            }}
          >
            {isActive && (
              <span
                style={{
                  display:     "inline-block",
                  width:       5,
                  height:      5,
                  borderRadius:"50%",
                  background:  "#00e5ff",
                  boxShadow:   "0 0 6px #00e5ff",
                  flexShrink:  0,
                }}
              />
            )}
            {city.label}
          </button>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BottomBar
// Fixed bottom panel containing legend + city selector
// ─────────────────────────────────────────────────────────────────────────────

export default function BottomBar({ activeCity, onSelectCity }) {
  return (
    <div
      className="slide-in-up"
      style={{
        position:      "fixed",
        bottom:        0,
        left:          0,
        right:         0,
        zIndex:        30,
        padding:       "0 20px 36px", // 36px = above 22px status bar
        animationDelay:"0.2s",
      }}
    >
      <SeverityLegend />
      <CitySelector activeCity={activeCity} onSelect={onSelectCity} />
    </div>
  );
}

import { LAYER_CONFIG } from "../../constants/layers";

// ─────────────────────────────────────────────────────────────────────────────
// LayerChip — click-style pill button (no toggle switch)
// ─────────────────────────────────────────────────────────────────────────────

function LayerChip({ config, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        padding: "8px 10px",
        background: active ? "rgba(0,229,255,0.1)" : "rgba(11,15,20,0.72)",
        border: active ? "1px solid rgba(0,229,255,0.42)" : "1px solid rgba(0,229,255,0.12)",
        borderRadius: 6,
        color: active ? "rgba(0,229,255,0.9)" : "rgba(200,214,229,0.55)",
        fontFamily: "'DM Mono', monospace",
        cursor: "pointer",
        boxShadow: active ? "0 0 14px rgba(0,229,255,0.14), inset 0 0 8px rgba(0,229,255,0.05)" : "none",
        transition: "all 0.22s ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: "10px", width: 12 }}>
          {config.icon}
        </span>
        <div>
          <div style={{ fontSize: "0.62rem", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            {config.label}
          </div>
          <div
            style={{
              fontSize: "0.5rem",
              color: "var(--text-faint)",
              letterSpacing: "0.04em",
              marginTop: 1,
            }}
          >
            {config.desc}
          </div>
        </div>
      </div>

      {active && (
        <span
          style={{
            marginLeft: "auto",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#00e5ff",
            boxShadow: "0 0 7px #00e5ff",
            flexShrink: 0,
          }}
        />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LayerControls
// Floating left-side panel: data layer chips
// ─────────────────────────────────────────────────────────────────────────────

export default function LayerControls({ activeLayers, onToggleLayer }) {

  return (
    <div
      className="slide-in-left"
      style={{
        position: "fixed",
        top: "50%",
        left: 20,
        transform: "translateY(-50%)",
        zIndex: 30,
        width: 252,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        animationDelay: "0.1s",
      }}
    >
      {/* Layer chips */}
      <div className="glass" style={{ padding: "10px" }}>
        {/* Header */}
        <div
          style={{
            padding: "0 4px 8px",
            borderBottom: "1px solid rgba(0,229,255,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
          }}
        >
          <span
            style={{
              fontSize: "0.55rem",
              letterSpacing: "0.22em",
              color: "var(--text-dim)",
              textTransform: "uppercase",
            }}
          >
            Metric Layers
          </span>
        </div>

        {/* Click chips */}
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          {Object.values(LAYER_CONFIG).map((cfg) => (
            <LayerChip
              key={cfg.id}
              config={cfg}
              active={activeLayers[cfg.id]}
              onClick={() => onToggleLayer(cfg.id)}
            />
          ))}
        </div>
      </div>

    </div>
  );
}

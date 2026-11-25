import { LAYER_CONFIG } from "../../constants/layers";


// ─────────────────────────────────────────────────────────────────────────────
// LayerChip — click-style pill button (no toggle switch)
// ─────────────────────────────────────────────────────────────────────────────

function LayerChip({ config, active, onClick, prov }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        boxSizing: "border-box",
        overflow: "hidden",
        textAlign: "left",
        padding: "5px 8px",
        height: 48,
        minHeight: 48,
        maxHeight: 48,
        background: active ? "rgba(0,229,255,0.1)" : "rgba(11,15,20,0.72)",
        border: active
          ? "1px solid rgba(0,229,255,0.42)"
          : "1px solid rgba(0,229,255,0.12)",
        borderRadius: 6,
        color: active ? "rgba(0,229,255,0.9)" : "rgba(200,214,229,0.55)",
        fontFamily: "'DM Mono', monospace",
        cursor: "pointer",
        boxShadow: active
          ? "0 0 14px rgba(0,229,255,0.14), inset 0 0 8px rgba(0,229,255,0.05)"
          : "none",
        transition: "all 0.22s ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span
          style={{
            fontSize: "11px",
            width: 24,
            textAlign: "center",
            color: active ? "rgba(0,229,255,0.9)" : "var(--text-dim)",
          }}
        >
          {config.icon}
        </span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: "0.56rem",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {config.label}
          </div>
          <div
            style={{
              fontSize: "0.44rem",
              color: "var(--text-faint)",
              letterSpacing: "0.04em",
              marginTop: 1,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
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


export default function LayerControls({
  activeLayers,
  onToggleLayer,
  aqiSurfaceStatus,
  aqiSurfaceInfo = null,
  provenance = null,
}) {
  return (
    <div
      className="slide-in-left"
      style={{
        position: "fixed",
        top: 190,
        left: 20,
        zIndex: 35,
        width: 230,
        height: 330,
        minWidth: 230,
        maxWidth: 230,
        minHeight: 330,
        maxHeight: 330,
        display: "block",
        overflow: "hidden",
        boxSizing: "border-box",
        animationDelay: "0.1s",
      }}
    >
      {/* Layer chips */}
      <div className="glass" style={{ width: "100%", height: "100%", boxSizing: "border-box", padding: "10px", overflow: "hidden" }}>
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
              prov={null}
            />
          ))}
        </div>
        {activeLayers.aqi &&
          !activeLayers.all &&
          ["unavailable", "error"].includes(aqiSurfaceStatus) && (
            <div
              role="status"
              aria-live="polite"
              style={{
                marginTop: 8,
                padding: "8px 2px 2px",
                borderTop: "1px solid rgba(255,140,0,0.3)",
                color: "rgba(255,211,170,0.9)",
                fontSize: "0.55rem",
                lineHeight: 1.5,
              }}
            >
              <strong
                style={{ display: "block", color: "#ffd3aa", fontWeight: 500 }}
              >
                AQI surface unavailable
              </strong>
              {aqiSurfaceStatus !== "unavailable"
                ? "The AQI surface source could not be read."
                : aqiSurfaceInfo?.status === "not_generated"
                  ? "This city's AQI layer has not been generated yet."
                  : aqiSurfaceInfo?.reason ||
                    "Not enough fresh CPCB-network stations for a real AQI surface."}
              {aqiSurfaceInfo?.audit?.stations_eligible != null && (
                <span style={{ display: "block", marginTop: 4, opacity: 0.8 }}>
                  Fresh stations: {aqiSurfaceInfo.audit.stations_eligible} /
                  needed {aqiSurfaceInfo.audit.minimum_stations}
                </span>
              )}
            </div>
          )}
      </div>

    </div>
  );
}

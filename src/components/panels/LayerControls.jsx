import { LAYER_CONFIG } from "../../constants/layers";

// ─────────────────────────────────────────────────────────────────────────────
// Toggle — reusable switch
// ─────────────────────────────────────────────────────────────────────────────

function Toggle({ on, onToggle }) {
  return (
    <div
      className={`toggle-track ${on ? "on" : ""}`}
      onClick={onToggle}
      role="switch"
      aria-checked={on}
    >
      <div className="toggle-thumb" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LayerRow — single toggle row inside the layer panel
// ─────────────────────────────────────────────────────────────────────────────

function LayerRow({ config, on, onToggle }) {
  return (
    <div
      className="layer-row"
      onClick={onToggle}
      style={{
        display:       "flex",
        alignItems:    "center",
        justifyContent:"space-between",
        padding:       "9px 14px",
        borderBottom:  "1px solid rgba(0,229,255,0.06)",
        cursor:        "pointer",
        transition:    "background 0.2s ease",
      }}
    >
      <div style={{ display:"flex", alignItems:"center", gap:10 }}>
        <span style={{ fontSize:"10px", color:"var(--text-dim)", width:12 }}>
          {config.icon}
        </span>
        <div>
          <div style={{ fontSize:"0.7rem", color:"var(--text)", letterSpacing:"0.06em" }}>
            {config.label}
          </div>
          <div
            style={{
              fontSize:     "0.55rem",
              color:        "var(--text-faint)",
              letterSpacing:"0.04em",
              marginTop:    1,
            }}
          >
            {config.desc}
          </div>
        </div>
      </div>

      <Toggle on={on} onToggle={(e) => { e.stopPropagation(); onToggle(); }} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ParameterSlider — single labeled range input
// ─────────────────────────────────────────────────────────────────────────────

function ParameterSlider({ label, defaultValue, onChange }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          display:       "flex",
          justifyContent:"space-between",
          fontSize:      "0.58rem",
          color:         "var(--text-dim)",
          letterSpacing: "0.06em",
          marginBottom:  5,
        }}
      >
        <span>{label}</span>
      </div>
      <input
        type="range"
        min="0"
        max="100"
        defaultValue={defaultValue}
        onChange={(e) => onChange?.(Number(e.target.value))}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LayerControls
// Floating right-side panel: data layer toggles + analysis parameters
// ─────────────────────────────────────────────────────────────────────────────

export default function LayerControls({ activeLayers, onToggleLayer, onParamChange }) {
  return (
    <div
      className="slide-in-right"
      style={{
        position:      "fixed",
        top:           90,
        right:         20,
        zIndex:        30,
        width:         192,
        display:       "flex",
        flexDirection: "column",
        gap:           8,
        animationDelay:"0.1s",
      }}
    >
      {/* Layer toggles */}
      <div className="glass" style={{ overflow:"hidden" }}>
        {/* Header */}
        <div
          style={{
            padding:      "8px 14px",
            borderBottom: "1px solid rgba(0,229,255,0.1)",
            display:      "flex",
            alignItems:   "center",
            justifyContent:"space-between",
          }}
        >
          <span
            style={{
              fontSize:     "0.55rem",
              letterSpacing:"0.22em",
              color:        "var(--text-dim)",
              textTransform:"uppercase",
            }}
          >
            Data Layers
          </span>
          <div
            style={{
              width:        18,
              height:       18,
              border:       "1px solid var(--border)",
              borderRadius: 3,
              display:      "flex",
              alignItems:   "center",
              justifyContent:"center",
              cursor:       "pointer",
              fontSize:     "10px",
              color:        "var(--cyan)",
            }}
          >
            +
          </div>
        </div>

        {/* Toggle rows */}
        {Object.values(LAYER_CONFIG).map((cfg) => (
          <LayerRow
            key={cfg.id}
            config={cfg}
            on={activeLayers[cfg.id]}
            onToggle={() => onToggleLayer(cfg.id)}
          />
        ))}
      </div>

      {/* Parameters */}
      <div className="glass" style={{ padding:"12px 14px" }}>
        <div
          style={{
            fontSize:     "0.52rem",
            letterSpacing:"0.22em",
            color:        "var(--text-dim)",
            marginBottom: 10,
            textTransform:"uppercase",
          }}
        >
          Parameters
        </div>

        <ParameterSlider
          label="Sensitivity"
          defaultValue={72}
          onChange={(v) => onParamChange?.("sensitivity", v)}
        />
        <ParameterSlider
          label="Radius"
          defaultValue={55}
          onChange={(v) => onParamChange?.("radius", v)}
        />
        <ParameterSlider
          label="Threshold"
          defaultValue={38}
          onChange={(v) => onParamChange?.("threshold", v)}
        />
      </div>
    </div>
  );
}

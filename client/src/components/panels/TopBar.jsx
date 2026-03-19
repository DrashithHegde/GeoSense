// ─────────────────────────────────────────────────────────────────────────────
// TopBar
// Floating header with GeoSense logo (left) and live REC / coords (right)
// ─────────────────────────────────────────────────────────────────────────────

export default function TopBar({ activeLayers, recTime, coords }) {
  const primaryLayer =
    Object.entries(activeLayers).find(([, v]) => v)?.[0]?.toUpperCase() || "—";

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 30,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        padding: "16px 22px 0",
        pointerEvents: "none",
      }}
    >
      {/* ── Logo ─────────────────────────────────────────────────────────── */}
      <div className="slide-in-left" style={{ pointerEvents: "all" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          {/* Wordmark only — no icon */}
          <div>
            <div
              style={{
                fontFamily: "'Syne', sans-serif",
                fontSize: "1.1rem",
                fontWeight: 700,
                letterSpacing: "0.14em",
                color: "rgba(255,255,255,0.88)",
                textShadow: "0 0 20px rgba(0,229,255,0.35)",
                lineHeight: 1,
              }}
            >
              GeoSense
            </div>
            <div
              style={{
                fontSize: "0.5rem",
                letterSpacing: "0.24em",
                color: "rgba(0,229,255,0.5)",
                textTransform: "uppercase",
                marginTop: 2,
              }}
            >
              Environmental Intelligence
            </div>
          </div>
        </div>

        {/* Classification tag */}
        <div
          style={{
            marginTop: 6,
            fontSize: "0.52rem",
            letterSpacing: "0.18em",
            color: "rgba(255,211,42,0.55)",
          }}
        >
          ENV-SIG // REAL-TIME // CLASSIFIED
        </div>
      </div>

      {/* ── Right — REC badge + telemetry ────────────────────────────────── */}
      <div
        className="slide-in-right"
        style={{ textAlign: "right", pointerEvents: "none" }}
      >
        {/* REC badge */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: 6,
            fontSize: "0.62rem",
            color: "rgba(255,59,59,0.85)",
            letterSpacing: "0.1em",
          }}
        >
          <div
            className="rec-blink"
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "#ff3b3b",
              boxShadow: "0 0 8px #ff3b3b",
            }}
          />
          <span style={{ fontFamily: "'DM Mono', monospace" }}>
            REC {recTime}
          </span>
        </div>

        {/* Coordinates */}
        <div
          style={{
            marginTop: 4,
            fontSize: "0.56rem",
            color: "rgba(0,229,255,0.55)",
            letterSpacing: "0.1em",
            fontFamily: "'DM Mono', monospace",
          }}
        >
          LAT: {coords.lat}° N · LNG: {coords.lng}° E
        </div>

        {/* Active layer label */}
        <div
          style={{
            marginTop: 2,
            fontSize: "0.5rem",
            letterSpacing: "0.2em",
            color: "rgba(200,214,229,0.28)",
          }}
        >
          ACTIVE LAYER: {primaryLayer}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// IntroOverlay — satellite mission boot screen
// Phases: "in" (full screen), "out" (fading), "done" (unmounted)
// ─────────────────────────────────────────────────────────────────────────────

const BOOT_LINES = [
  "SENSOR ARRAY.............. ONLINE",
  "SPECTRAL BANDS............ CALIBRATED",
  "NDVI / NDWI / LST / AQI.. READY",
  "ANOMALY DETECTION......... ACTIVE",
];

export default function IntroOverlay({ phase }) {
  if (phase === "done") return null;

  return (
    <div
      className={phase === "in" ? "intro-fade-in" : "intro-fade-out"}
      style={{
        position: "absolute", inset: 0, zIndex: 80,
        background: "#050a10",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        overflow: "hidden",
      }}
    >
      {/* ── Satellite grid overlay ─────────────────────────────────────── */}
      <svg
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.06, pointerEvents: "none" }}
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <pattern id="sat-grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M 60 0 L 0 0 0 60" fill="none" stroke="#d97f2a" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#sat-grid)" />
      </svg>

      {/* ── Horizontal scan line ───────────────────────────────────────── */}
      <div style={{
        position: "absolute", left: 0, right: 0, height: 1,
        background: "linear-gradient(to right, transparent 0%, rgba(217,127,42,0.18) 20%, rgba(217,127,42,0.5) 50%, rgba(217,127,42,0.18) 80%, transparent 100%)",
        animation: "satScan 5s ease-in-out infinite",
        pointerEvents: "none",
      }} />

      {/* ── Corner brackets ───────────────────────────────────────────── */}
      {[
        { top: 20, left: 20, borderTop: "1px solid", borderLeft: "1px solid" },
        { top: 20, right: 20, borderTop: "1px solid", borderRight: "1px solid" },
        { bottom: 20, left: 20, borderBottom: "1px solid", borderLeft: "1px solid" },
        { bottom: 20, right: 20, borderBottom: "1px solid", borderRight: "1px solid" },
      ].map((s, i) => (
        <div key={i} style={{
          position: "absolute", ...s,
          width: 32, height: 32,
          borderColor: "rgba(217,127,42,0.5)",
          pointerEvents: "none",
        }} />
      ))}

      {/* ── Top telemetry bar ─────────────────────────────────────────── */}
      <div style={{
        position: "absolute", top: 22, left: 0, right: 0,
        display: "flex", justifyContent: "space-between", padding: "0 62px",
        fontFamily: "'DM Mono', monospace", fontSize: "0.5rem",
        letterSpacing: "0.2em", color: "rgba(217,127,42,0.6)", textTransform: "uppercase",
      }}>
        <span>SAT-ENV // v3.0 // GSD: 10M</span>
        <span>SYS BOOT // LINK ACTIVE</span>
      </div>

      {/* ── GEOSENSE wordmark ────────────────────────────────────────────── */}
      <div style={{
        fontFamily: "'Syne', sans-serif",
        fontSize: "3.6rem", fontWeight: 800,
        letterSpacing: "0.28em", color: "#ffffff",
        textShadow: "0 0 30px rgba(217,127,42,0.6), 0 0 80px rgba(217,127,42,0.2)",
        lineHeight: 1,
        marginTop: "50px",
      }}>
        GEOSENSE
      </div>

      {/* ── Hair-line divider ──────────────────────────────────────────── */}
      <div style={{
        width: 320, height: 1, margin: "16px 0 18px",
        background: "linear-gradient(to right, transparent, rgba(217,127,42,0.6), transparent)",
      }} />

      {/* ── Boot sequence lines ───────────────────────────────────────── */}
      <div style={{
        display: "flex", flexDirection: "column", gap: 5,
        fontFamily: "'DM Mono', monospace", fontSize: "0.52rem",
        letterSpacing: "0.14em", textTransform: "uppercase",
      }}>
        {BOOT_LINES.map((line, i) => (
          <div key={i} style={{
            color: i < 3 ? "rgba(217,127,42,0.75)" : "rgba(217,127,42,0.85)",
            animation: `introFadeIn ${0.4 + i * 0.18}s ease both`,
          }}>
            {i < 3 ? `[ OK ] ${line}` : `[ ██ ] ${line}`}
          </div>
        ))}
      </div>

      {/* ── Coordinate readout ────────────────────────────────────────── */}
      <div style={{
        marginTop: 28,
        fontFamily: "'DM Mono', monospace", fontSize: "0.5rem",
        letterSpacing: "0.16em", color: "rgba(217,127,42,0.4)",
        textTransform: "uppercase",
      }}>
        LAT: 20.5937° N &nbsp;·&nbsp; LNG: 78.9629° E &nbsp;·&nbsp; ALT: 705 KM
      </div>

      {/* ── Bottom classification ─────────────────────────────────────── */}
      <div style={{
        position: "absolute", bottom: 22, left: 0, right: 0,
        textAlign: "center",
        fontFamily: "'DM Mono', monospace", fontSize: "0.46rem",
        letterSpacing: "0.2em", color: "rgba(217,127,42,0.35)",
        textTransform: "uppercase",
      }}>
        Environmental Intelligence Platform &nbsp;·&nbsp; Real-time Satellite Analysis
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Toast
// Centered, timed notification bar that slides in/out from the top
// ─────────────────────────────────────────────────────────────────────────────

export default function Toast({ message, phase }) {
  if (!message) return null;

  return (
    <div
      className={phase === "in" ? "toast-in" : "toast-out"}
      style={{
        position: "fixed",
        top: 82,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 60,
        background: "rgba(0,229,255,0.08)",
        border: "1px solid rgba(0,229,255,0.22)",
        borderRadius: 4,
        padding: "6px 18px",
        fontFamily: "'DM Mono', monospace",
        fontSize: "0.58rem",
        letterSpacing: "0.14em",
        color: "rgba(0,229,255,0.82)",
        whiteSpace: "nowrap",
        backdropFilter: "blur(14px)",
        boxShadow: "0 0 14px rgba(0,229,255,0.08)",
        pointerEvents: "none",
      }}
    >
      {message}
    </div>
  );
}

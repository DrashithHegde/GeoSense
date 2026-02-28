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
        position:      "fixed",
        top:           82,
        left:          "50%",
        transform:     "translateX(-50%)",
        zIndex:        60,
        background:    "rgba(0,229,255,0.09)",
        border:        "1px solid rgba(0,229,255,0.3)",
        borderRadius:  4,
        padding:       "7px 22px",
        fontFamily:    "'DM Mono', monospace",
        fontSize:      "0.6rem",
        letterSpacing: "0.18em",
        color:         "rgba(0,229,255,0.9)",
        whiteSpace:    "nowrap",
        backdropFilter:"blur(16px)",
        boxShadow:     "0 0 24px rgba(0,229,255,0.12)",
        pointerEvents: "none",
      }}
    >
      {message}
    </div>
  );
}

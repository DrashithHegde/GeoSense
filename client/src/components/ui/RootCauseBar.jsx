// ─────────────────────────────────────────────────────────────────────────────
// RootCauseBar
// Single row in the root-cause breakdown: icon + label + progress bar + value
// ─────────────────────────────────────────────────────────────────────────────

export default function RootCauseBar({ icon, label, value, color, normalizedValue, displayValue }) {
  const barWidth = typeof normalizedValue === "number"
    ? Math.max(0, Math.min(100, normalizedValue))
    : Math.max(0, Math.min(100, Number(value) || 0));

  const rightText = displayValue ?? value;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 10,
      }}
    >
      <span style={{ fontSize: "11px", width: 14, flexShrink: 0 }}>
        {icon}
      </span>

      <span
        style={{
          fontSize: "0.58rem",
          color: "var(--text-dim)",
          letterSpacing: "0.08em",
          width: 52,
          flexShrink: 0,
        }}
      >
        {label}
      </span>

      <div
        style={{
          flex: 1,
          height: 2,
          background: "rgba(255,255,255,0.06)",
          borderRadius: 1,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${barWidth}%`,
            background: color,
            borderRadius: 1,
            boxShadow: `0 0 6px ${color}`,
            transition: "width 0.9s cubic-bezier(0.22,1,0.36,1)",
          }}
        />
      </div>

      <span
        style={{
          fontSize: "0.58rem",
          color,
          width: 28,
          textAlign: "right",
          letterSpacing: "0em",
          fontFamily: "'DM Mono', monospace",
          fontWeight: 400,
          flexShrink: 0,
        }}
      >
        {rightText}
      </span>
    </div>
  );
}

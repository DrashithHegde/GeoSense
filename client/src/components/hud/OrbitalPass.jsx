// ─────────────────────────────────────────────────────────────────────────────
// OrbitalPass
// Top-right orbital pass & time metadata overlay
// ─────────────────────────────────────────────────────────────────────────────

export default function OrbitalPass({ recTime }) {
    const now = new Date();
    const dateStr = now.toISOString().split("T")[0];
    const timeStr = now.toISOString().split("T")[1].slice(0, 8);

    return (
        <div
            style={{
                position: "fixed",
                top: 100,
                right: 12,
                zIndex: 20,
                fontFamily: "'DM Mono', monospace",
                fontSize: "0.65rem",
                letterSpacing: "0.15em",
                color: "rgba(217,127,42,0.75)",
                textShadow: "0 0 8px rgba(217, 127, 42, 0.5)",
                pointerEvents: "none",
                lineHeight: 1.6,
                textAlign: "right",
            }}
        >
            <div style={{ fontSize: "0.55rem", opacity: 0.85, marginBottom: 6 }}>
                SCAN {dateStr} {timeStr}Z
            </div>
            <div style={{ fontSize: "0.55rem", opacity: 0.85, marginBottom: 3 }}>
                ZONE: INDIA-GRID PASS: ACTIVE-526
            </div>
            <div style={{ fontSize: "0.55rem", opacity: 0.85 }}>
                DATA ACQUISITION • NOMINAL STATUS
            </div>
        </div>
    );
}

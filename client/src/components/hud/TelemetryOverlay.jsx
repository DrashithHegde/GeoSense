// ─────────────────────────────────────────────────────────────────────────────
// TelemetryOverlay
// Bottom-right technical telemetry & geospatial specs overlay
// ─────────────────────────────────────────────────────────────────────────────

export default function TelemetryOverlay({ coords = {} }) {
    const lat = coords.lat || "20.5937";
    const lng = coords.lng || "78.9629";

    return (
        <div
            style={{
                position: "fixed",
                bottom: 30,
                right: 12,
                zIndex: 40,
                fontFamily: "'DM Mono', monospace",
                fontSize: "0.62rem",
                letterSpacing: "0.12em",
                color: "#d97f2a",
                textShadow: "0 0 8px rgba(217, 127, 42, 0.5)",
                pointerEvents: "none",
                lineHeight: 1.8,
                textAlign: "right",
            }}
        >
            <div
                style={{
                    fontSize: "0.55rem",
                    animation: "glowPulse 3s ease-in-out infinite",
                }}
            >
                RESOLUTION: 10M QUALITY: 8.7
            </div>
            <div
                style={{
                    fontSize: "0.55rem",
                    animation: "fadeFlicker 2.5s ease-in-out infinite",
                }}
            >
                COVERAGE: ACTIVE • CLOUD FREE
            </div>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// ClassificationHeader
// Top-left intelligence/surveillance agency classification overlay
// Positioned below the logo to avoid overlap
// ─────────────────────────────────────────────────────────────────────────────

export default function ClassificationHeader() {
    return (
        <div
            style={{
                position: "fixed",
                top: 100,
                left: 12,
                zIndex: 40,
                fontFamily: "'DM Mono', monospace",
                fontSize: "0.65rem",
                letterSpacing: "0.15em",
                color: "#d97f2a",
                textShadow: "0 0 8px rgba(217, 127, 42, 0.5)",
                pointerEvents: "none",
                lineHeight: 1.6,
            }}
        >
            <div style={{ fontWeight: 700, marginBottom: 6 }}>
                TOP SECRET // GEOSENSE // NOFORN
            </div>
            <div style={{ fontSize: "0.55rem", opacity: 0.85 }}>
                SENTINEL-02 GEO-4208
            </div>
            <div style={{ fontSize: "0.55rem", opacity: 0.85, marginTop: 3 }}>
                CRT
            </div>

            {/* Typewriter animation for mission summary */}
            <div
                className="typewriter-text"
                style={{
                    marginTop: 4,
                    fontSize: "0.45rem",
                    opacity: 0.7,
                    height: "1.2em",
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    fontFamily: "'DM Mono', monospace",
                }}
            >
                SUMMARY GEOSENSE URBAN MONITORING (INDIA) 8824KM ACTIVE
            </div>
        </div>
    );
}

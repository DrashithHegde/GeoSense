import { LAYER_CONFIG } from "../../constants/layers";
import { getMetricDisplay, getZoneMetrics } from "../../utils/helpers";

export default function EnvironmentMetrics({ activeLayers, selectedZone }) {
    // Get active layer names
    const activeLayerNames = Object.entries(activeLayers)
        .filter(([, on]) => on)
        .map(([id]) => id);

    // Get metrics from selected zone or show placeholder
    const getMetricsDisplay = () => {
        if (!selectedZone) {
            return <div style={{ color: "var(--text-faint)" }}>Select a zone for metrics</div>;
        }

        return (
            <div style={{ display: "flex", gap: 24 }}>
                {activeLayerNames.map((layerId) => {
                    const layer = LAYER_CONFIG[layerId];
                    const metrics = getZoneMetrics(selectedZone);
                    const value = getMetricDisplay(layerId, metrics);

                    if (layerId === "all") {
                        return (
                            <div key={layerId} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                <div style={{ fontSize: "0.55rem", color: "var(--text-faint)", letterSpacing: "0.06em" }}>
                                    {layer.label.toUpperCase()}
                                </div>
                                <div style={{ fontSize: "1rem", color: "var(--cyan)", fontWeight: "bold" }}>
                                    Severity {selectedZone.severity.toFixed(1)}
                                </div>
                                <div style={{ fontSize: "0.5rem", color: "var(--text-dim)" }}>
                                    Composite anomaly index
                                </div>
                            </div>
                        );
                    }

                    return (
                        <div key={layerId} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <div style={{ fontSize: "0.55rem", color: "var(--text-faint)", letterSpacing: "0.06em" }}>
                                {layer.label.toUpperCase()}
                            </div>
                            <div style={{ fontSize: "1rem", color: "var(--cyan)", fontWeight: "bold" }}>
                                {value}
                            </div>
                            <div style={{ fontSize: "0.5rem", color: "var(--text-dim)" }}>
                                {layer.desc}
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    return (
        <div
            className="glass slide-in-up"
            style={{
                position: "fixed",
                top: 68,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 30,
                padding: "12px 20px",
                borderRadius: "10px",
                minWidth: "340px",
                maxWidth: "520px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 8,
            }}
        >
            <div style={{ fontSize: "0.62rem", color: "rgba(0,229,255,0.5)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
                Environment Metrics
            </div>
            <div>{getMetricsDisplay()}</div>
        </div>
    );
}

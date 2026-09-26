import { memo, useEffect, useMemo, useState } from "react";
import { getAqiCpcbBand, getLstBand, getNdviBand, getWaterHealthBand, getSeverityColor, getSeverityLabel, getZoneMetrics, getMetricDisplay, normalizeMetric } from "../../utils/helpers";
import TrendSparkline from "../ui/TrendSparkline";
import RootCauseBar from "../ui/RootCauseBar";

const LAYER_PRIORITY = ["aqi", "ndvi", "water_health", "lst"];
const COMPOSITE_ACCENT_COLOR = "#b45309";

const LAYER_META = {
    composite: { icon: "⬡", label: "Composite", color: COMPOSITE_ACCENT_COLOR },
    aqi: { icon: "○", label: "AQI", color: "#ff8c00" },
    ndvi: { icon: "◇", label: "NDVI", color: "#1dd1a1" },
    water_health: { icon: "◈", label: "Water Health", color: "#00b4d8" },
    lst: { icon: "▣", label: "LST", color: "#ff5f57" },
};

const ANALYSIS_MODE_ORDER = ["composite", "aqi", "ndvi", "water_health", "lst"];

function getUserFacingExplanation(text) {
    if (!text) return "Analysis unavailable.";
    return text
        .split("\n")
        .filter((line) => !/NDWI|Normalized Difference Water Index|Water Index/i.test(line))
        .join("\n")
        .trim();
}

const LAYER_REFERENCE = {
    composite: {
        metric: "Composite Risk Score (0-100)",
        definition: "Backend Composite stress score combining AQI, NDVI, LST, and Water Health where available.",
        method: "Weighted multi-metric anomaly fusion",
        bands: [
            { range: "0-24", label: "GOOD" },
            { range: "25-49", label: "MODERATE" },
            { range: "50-69", label: "HIGH" },
            { range: "70-84", label: "SEVERE" },
            { range: "85-100", label: "CRITICAL" },
        ],
    },
    aqi: {
        metric: "CPCB AQI (0-500)",
        definition: "National Air Quality Index representing ambient air pollution burden.",
        method: "CPCB AQI band classification",
        bands: [
            { range: "0-50", label: "GOOD" },
            { range: "51-100", label: "SATISFACTORY" },
            { range: "101-200", label: "MODERATE" },
            { range: "201-300", label: "POOR" },
            { range: "301-400", label: "VERY POOR" },
            { range: "401-500", label: "SEVERE" },
        ],
    },
    ndvi: {
        metric: "NDVI (-1 to 1)",
        definition: "Normalized Difference Vegetation Index indicating vegetation density and vigor.",
        method: "(NIR - Red) / (NIR + Red)",
        bands: [
            { range: "< 0.00", label: "NON-VEGETATED" },
            { range: "0.00-0.19", label: "VERY LOW VEGETATION" },
            { range: "0.20-0.39", label: "LOW VEGETATION" },
            { range: "0.40-0.59", label: "MODERATE VEGETATION" },
            { range: ">= 0.60", label: "HIGH VEGETATION" },
        ],
    },
    water_health: {
        metric: "Water Health (0-100%)",
        definition: "Water condition indicator available only where MNDWI detects water.",
        method: "Algal-related and suspended-material spectral proxies with temporal evidence",
        bands: [
            { range: "75-100%", label: "GOOD CONDITION" },
            { range: "50-74%", label: "WATCH" },
            { range: "0-49%", label: "POTENTIAL CONCERN" },
        ],
    },
    lst: {
        metric: "LST (°C)",
        definition: "Land Surface Temperature derived from thermal infrared response.",
        method: "Surface thermal emission proxy (°C)",
        bands: [
            { range: "< 28°C", label: "COOL" },
            { range: "28-31.9°C", label: "MILD" },
            { range: "32-35.9°C", label: "WARM" },
            { range: "36-39.9°C", label: "HOT" },
            { range: ">= 40°C", label: "EXTREME HEAT" },
        ],
    },
};

// ─────────────────────────────────────────────────────────────────────────────
// DeepAnalysisOverlay
// ─────────────────────────────────────────────────────────────────────────────

export default function DeepAnalysisOverlay({
    zone,
    pointAnalysis,
    cityLabel,
    explanationData,
    activeLayers,
    isOpen,
    onClose,
}) {
    const metrics = zone ? getZoneMetrics(zone) : null;
    const activeLayerId = resolveActiveLayerId(activeLayers);

    // Default to composite if no layers are active
    const analysisMode = activeLayerId === "all" ? "composite" : activeLayerId;

    const [activeTab, setActiveTab] = useState(analysisMode);

    useEffect(() => {
        if (isOpen) setActiveTab(analysisMode);
    }, [isOpen, analysisMode]);

    if (!zone || !metrics) return null;

    // Extract point analysis hierarchy — prefer explicit prop, fall back to attached data
    const pixel = pointAnalysis?.pixel || zone?.pointAnalysis?.pixel || null;
    const cell = pointAnalysis?.cell || zone?.pointAnalysis?.cell || null;
    const municipality = pointAnalysis?.municipality || zone?.pointAnalysis?.municipality || null;

    // Convenience: pixel-level values (exact satellite pixel)
    const pixelNdvi = pixel?.ndvi && !pixel.ndvi.nodata ? pixel.ndvi.value : null;
    const pixelLst = pixel?.lst && !pixel.lst.nodata ? pixel.lst.value_c : null;
    const pixelAqi = pixel?.aqi && !pixel.aqi.nodata ? pixel.aqi.value : null;
    const pixelWaterHealth = pixel?.water_health && !pixel.water_health.nodata ? pixel.water_health.value : null;

    // Convenience: cell-level aggregated values (300m grid)
    const cellMetrics = cell?.metrics || {};
    const cellNdvi = cellMetrics.ndvi ?? null;
    const cellLst = cellMetrics.lst ?? null;
    const cellAqi = cellMetrics.aqi ?? null;
    const cellWater = cellMetrics.water_health_score ?? null;
    const cellAnomaly = cell?.anomaly || null;

    const layerMeta = LAYER_REFERENCE[activeTab];
    const isCompositeView = activeTab === "composite";

    const stressValue = isCompositeView
        ? zone?.composite?.score ?? null
        : normalizeMetric(activeTab, metrics);

    const severityScore = isCompositeView ? (zone?.severity ?? 0) : stressValue;

    const severityLabel = (() => {
        if (activeTab === "aqi") return getAqiCpcbBand(metrics?.aqi);
        if (activeTab === "ndvi") return getNdviBand(metrics?.ndvi);
        if (activeTab === "water_health") return getWaterHealthBand(metrics?.water_health_score);
        if (activeTab === "lst") return getLstBand(metrics?.lst);
        return getSeverityLabel(severityScore);
    })();

    const severityColor = getSeverityColor(severityScore);
    const zoneDisplayName = cityLabel ? `${zone?.name}, ${cityLabel}` : zone?.name;

    // We keep MUMBAI_LOCATIONS_DATA as static context
    const locationData = MUMBAI_LOCATIONS_DATA[zone?.name];

    // Build metric cards — these are ALWAYS CELL aggregates, never pixel
    const metricCards = [
        {
            id: "aqi",
            label: "AQI · Cell Mean",
            value: metrics.aqi != null ? metrics.aqi : "N/A",
            norm: zone.composite?.contributions?.aqi == null ? null : zone.composite.contributions.aqi * 100,
            color: LAYER_META.aqi.color,
            unit: "",
        },
        {
            id: "lst",
            label: "LST · Cell Mean",
            value: metrics.lst !== null && metrics.lst !== undefined ? metrics.lst.toFixed(1) : "N/A",
            norm: zone.composite?.contributions?.lst == null ? null : zone.composite.contributions.lst * 100,
            color: LAYER_META.lst.color,
            unit: metrics.lst !== null && metrics.lst !== undefined ? "°C" : "",
        },
        {
            id: "ndvi",
            label: "NDVI · Cell Mean",
            value: metrics.ndvi != null ? metrics.ndvi.toFixed(2) : "N/A",
            norm: zone.composite?.contributions?.ndvi == null ? null : zone.composite.contributions.ndvi * 100,
            color: LAYER_META.ndvi.color,
            unit: "",
        },
        {
            id: "water_health",
            label: "Water · Cell Mean",
            value: metrics.water_health_score == null ? "N/A" : `${(metrics.water_health_score * 100).toFixed(0)}%`,
            norm: zone.composite?.contributions?.water_health == null ? null : zone.composite.contributions.water_health * 100,
            color: LAYER_META.water_health.color,
            unit: "",
        },
    ];

    // Classification
    const classification = explanationData?.classification
        ? explanationData.classification.toUpperCase()
        : cellAnomaly?.flag
            ? "ANOMALY"
            : zone?.is_anomaly
                ? "ANOMALY"
                : "INLIER";

    return (
        <div
            style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                zIndex: 60,
                backgroundColor: "rgba(3, 5, 8, 0.85)",
                backdropFilter: "blur(24px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                opacity: isOpen ? 1 : 0,
                pointerEvents: isOpen ? "auto" : "none",
                transition: "opacity 0.4s ease",
            }}
        >
            {/* Main Panel */}
            <div
                className="glass"
                style={{
                    width: "90%",
                    maxWidth: 1200,
                    height: "85%",
                    maxHeight: 900,
                    borderRadius: 16,
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                    border: "1px solid rgba(0, 229, 255, 0.15)",
                    boxShadow: "0 0 60px rgba(0, 229, 255, 0.05)",
                    transform: isOpen ? "scale(1) translateY(0)" : "scale(0.98) translateY(20px)",
                    transition: "all 0.5s cubic-bezier(0.22, 1, 0.36, 1)",
                }}
            >
                {/* ── Header ────────────────────────────────────────────── */}
                <div
                    style={{
                        padding: "24px 32px",
                        borderBottom: "1px solid rgba(0,229,255,0.1)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        flexShrink: 0,
                        position: "relative",
                        background: "linear-gradient(to bottom, rgba(0,229,255,0.03), transparent)",
                    }}
                >
                    {/* Left Header */}
                    <div>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 12,
                                marginBottom: 8,
                                flexWrap: "wrap",
                            }}
                        >
                            <div
                                style={{
                                    fontSize: "0.6rem",
                                    letterSpacing: "0.25em",
                                    color: classification === "ANOMALY" ? "rgba(255,59,59,0.8)" : "rgba(0,229,255,0.6)",
                                    textTransform: "uppercase",
                                    padding: "4px 8px",
                                    background: classification === "ANOMALY" ? "rgba(255,59,59,0.1)" : "rgba(0,229,255,0.05)",
                                    border: `1px solid ${classification === "ANOMALY" ? "rgba(255,59,59,0.3)" : "rgba(0,229,255,0.2)"}`,
                                    borderRadius: 4,
                                }}
                            >
                                DEEP ANALYSIS // {classification === "ANOMALY" ? "ANOMALY DETECTED" : "NOMINAL"}
                            </div>
                            <div
                                style={{
                                    fontSize: "0.6rem",
                                    letterSpacing: "0.2em",
                                    color: "#1dd1a1",
                                    padding: "3px 8px",
                                    background: "rgba(29,209,161,0.08)",
                                    border: "1px solid rgba(29,209,161,0.22)",
                                    borderRadius: 3,
                                    fontFamily: "'DM Mono', monospace",
                                }}
                            >
                                CELL ID: {cell?.id != null ? cell.id : zone.id}
                            </div>
                            {municipality?.name && (
                                <div
                                    style={{
                                        fontSize: "0.6rem",
                                        letterSpacing: "0.15em",
                                        color: "#00b4d8",
                                        padding: "3px 8px",
                                        background: "rgba(0,180,216,0.08)",
                                        border: "1px solid rgba(0,180,216,0.22)",
                                        borderRadius: 3,
                                    }}
                                >
                                    ADMIN · {municipality.name.toUpperCase()}
                                </div>
                            )}
                        </div>

                        <div
                            style={{
                                fontFamily: "'Syne', sans-serif",
                                fontSize: "2rem",
                                fontWeight: 700,
                                color: "rgba(255,255,255,0.95)",
                                letterSpacing: "0.02em",
                                lineHeight: 1.2,
                                marginBottom: 4,
                            }}
                        >
                            {zoneDisplayName}
                        </div>

                        <div
                            style={{
                                fontSize: "0.65rem",
                                color: "var(--text-dim)",
                                letterSpacing: "0.15em",
                                fontFamily: "'DM Mono', monospace",
                            }}
                        >
                            CLICKED COORDINATES: {
                                (pixel?.latitude ?? zone?.coords?.[1]) != null
                                    ? `${(pixel?.latitude ?? zone?.coords?.[1]).toFixed(5)}°N, ${(pixel?.longitude ?? zone?.coords?.[0]).toFixed(5)}°E`
                                    : "—"
                            }
                            {cell?.resolution_m ? `  ·  CELL GRID: ${cell.resolution_m}m ANALYTICAL` : ""}
                        </div>
                    </div>

                    {/* Right Header Controls */}
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 16 }}>
                        <button
                            onClick={onClose}
                            style={{
                                background: "none",
                                border: "1px solid rgba(0,229,255,0.3)",
                                borderRadius: 6,
                                color: "var(--text-dim)",
                                width: 36,
                                height: 36,
                                cursor: "pointer",
                                fontSize: "16px",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                transition: "all 0.2s ease",
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.color = "var(--cyan)";
                                e.currentTarget.style.borderColor = "rgba(0,229,255,0.6)";
                                e.currentTarget.style.boxShadow = "0 0 12px rgba(0,229,255,0.2)";
                                e.currentTarget.style.background = "rgba(0,229,255,0.05)";
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.color = "var(--text-dim)";
                                e.currentTarget.style.borderColor = "rgba(0,229,255,0.3)";
                                e.currentTarget.style.boxShadow = "none";
                                e.currentTarget.style.background = "none";
                            }}
                        >
                            ✕
                        </button>
                    </div>
                </div>

                {/* ── Spatial Hierarchy Banner (3 Distinct Levels) ──────── */}
                {(pixel || cell || municipality) && (
                    <div
                        style={{
                            padding: "16px 32px",
                            borderBottom: "1px solid rgba(0,229,255,0.1)",
                            background: "rgba(0,0,0,0.15)",
                            display: "grid",
                            gridTemplateColumns: "1fr 1.4fr 1fr",
                            gap: 16,
                            flexShrink: 0,
                        }}
                    >
                        {/* 1. PIXEL */}
                        <div
                            style={{
                                padding: "12px 14px",
                                background: "rgba(255, 95, 87, 0.04)",
                                border: "1px solid rgba(255, 95, 87, 0.18)",
                                borderLeft: "3px solid #ff5f57",
                                borderRadius: 6,
                            }}
                        >
                            <SpatialLevelHeader
                                level="1"
                                label="PIXEL"
                                sublabel="Exact satellite value"
                                accent="#ff5f57"
                            />
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px" }}>
                                <MetricRow
                                    label="NDVI"
                                    value={pixelNdvi != null ? pixelNdvi.toFixed(3) : (pixel?.ndvi?.nodata ? "NoData" : "N/A")}
                                    color="#1dd1a1"
                                    nodata={pixel?.ndvi?.nodata}
                                />
                                <MetricRow
                                    label="LST"
                                    value={pixelLst != null ? pixelLst.toFixed(1) : (pixel?.lst?.nodata ? "NoData" : "N/A")}
                                    unit="°C"
                                    color="#ff5f57"
                                    nodata={pixel?.lst?.nodata}
                                />
                                <MetricRow
                                    label="AQI"
                                    value={pixelAqi != null ? String(pixelAqi) : (pixel?.aqi?.nodata ? "NoData" : "N/A")}
                                    color="#ff8c00"
                                    nodata={pixel?.aqi?.nodata}
                                />
                                <MetricRow
                                    label="Water Health"
                                    value={pixelWaterHealth != null ? `${(pixelWaterHealth * 100).toFixed(0)}%` : (pixel?.water_health?.nodata ? "NoData" : "N/A")}
                                    color="#00b4d8"
                                    nodata={pixel?.water_health?.nodata}
                                />
                            </div>
                        </div>

                        {/* 2. CELL */}
                        <div
                            style={{
                                padding: "12px 14px",
                                background: "rgba(29, 209, 161, 0.04)",
                                border: "1px solid rgba(29, 209, 161, 0.18)",
                                borderLeft: "3px solid #1dd1a1",
                                borderRadius: 6,
                            }}
                        >
                            <SpatialLevelHeader
                                level="2"
                                label="LOCAL ANALYTICAL CELL"
                                sublabel={`${cell?.resolution_m || 300}m grid · zonal aggregates${cellAnomaly?.flag ? " · ANOMALY" : ""}`}
                                accent="#1dd1a1"
                            />
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "6px 10px" }}>
                                <MetricRow label="AQI" value={cellAqi != null ? String(cellAqi) : "N/A"} color="#ff8c00" />
                                <MetricRow label="NDVI" value={cellNdvi != null ? cellNdvi.toFixed(2) : "N/A"} color="#1dd1a1" />
                                <MetricRow label="LST" value={cellLst != null ? cellLst.toFixed(1) : "N/A"} unit="°C" color="#ff5f57" />
                                <MetricRow label="Water" value={cellWater != null ? `${(cellWater * 100).toFixed(0)}%` : "N/A"} color="#00b4d8" />
                            </div>
                            {cellAnomaly?.flag && cellAnomaly.score != null && (
                                <div style={{ fontSize: "0.55rem", color: "#ff3b3b", marginTop: 6, letterSpacing: "0.12em", fontFamily: "'DM Mono', monospace" }}>
                                    ⚠ ANOMALY SCORE: {cellAnomaly.score.toFixed(2)}
                                </div>
                            )}
                        </div>

                        {/* 3. MUNICIPALITY */}
                        <div
                            style={{
                                padding: "12px 14px",
                                background: "rgba(0, 180, 216, 0.04)",
                                border: "1px solid rgba(0, 180, 216, 0.18)",
                                borderLeft: "3px solid #00b4d8",
                                borderRadius: 6,
                                display: "flex",
                                flexDirection: "column",
                                justifyContent: "space-between",
                            }}
                        >
                            <SpatialLevelHeader
                                level="3"
                                label="MUNICIPALITY"
                                sublabel="Administrative context only"
                                accent="#00b4d8"
                            />
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                                <div>
                                    <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.1rem", fontWeight: 600, color: "rgba(255,255,255,0.92)" }}>
                                        {municipality?.name || "—"}
                                    </div>
                                    <div style={{ fontSize: "0.55rem", color: "var(--text-dim)", marginTop: 2, letterSpacing: "0.08em" }}>
                                        {municipality?.source || cell?.municipality_name_from_cell || "Administrative boundary"}
                                    </div>
                                </div>
                                <div
                                    style={{
                                        padding: "3px 8px",
                                        fontSize: "0.55rem",
                                        letterSpacing: "0.15em",
                                        color: "#00b4d8",
                                        background: "rgba(0,180,216,0.12)",
                                        border: "1px solid rgba(0,180,216,0.25)",
                                        borderRadius: 3,
                                    }}
                                >
                                    ADMIN
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── Tabs ──────────────────────────────────────────────── */}
                <div
                    style={{
                        display: "flex",
                        borderBottom: "1px solid rgba(0,229,255,0.1)",
                        padding: "0 32px",
                        flexShrink: 0,
                    }}
                >
                    {ANALYSIS_MODE_ORDER.map((mode) => {
                        const meta = LAYER_META[mode];
                        const isActive = activeTab === mode;
                        return (
                            <button
                                key={mode}
                                onClick={() => setActiveTab(mode)}
                                style={{
                                    padding: "16px 24px",
                                    background: "none",
                                    border: "none",
                                    borderBottom: `2px solid ${isActive ? meta.color : "transparent"}`,
                                    color: isActive ? "white" : "var(--text-dim)",
                                    fontFamily: "'DM Mono', monospace",
                                    fontSize: "0.65rem",
                                    letterSpacing: "0.15em",
                                    textTransform: "uppercase",
                                    cursor: "pointer",
                                    transition: "all 0.2s ease",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    opacity: isActive ? 1 : 0.6,
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive) e.currentTarget.style.opacity = 0.9;
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive) e.currentTarget.style.opacity = 0.6;
                                }}
                            >
                                <span style={{ color: meta.color, fontSize: "0.8rem" }}>{meta.icon}</span>
                                {meta.label} Analysis
                            </button>
                        );
                    })}
                </div>

                {/* ── Body ──────────────────────────────────────────────── */}
                <div
                    style={{
                        flex: 1,
                        display: "flex",
                        overflow: "hidden",
                    }}
                >
                    {/* Left Column (Primary Metrics & Evidence) */}
                    <div
                        style={{
                            flex: "1 1 60%",
                            padding: "32px",
                            overflowY: "auto",
                            borderRight: "1px solid rgba(0,229,255,0.1)",
                            display: "flex",
                            flexDirection: "column",
                            gap: 32,
                        }}
                    >
                        {/* 1. Core Assessment Block */}
                        <div style={{ display: "flex", gap: 24 }}>
                            {/* Score Display */}
                            <div
                                style={{
                                    flex: "0 0 200px",
                                    padding: "24px",
                                    background: "rgba(0,0,0,0.2)",
                                    border: "1px solid rgba(0,229,255,0.1)",
                                    borderRadius: 12,
                                    display: "flex",
                                    flexDirection: "column",
                                    justifyContent: "center",
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: "0.6rem",
                                        letterSpacing: "0.15em",
                                        color: "var(--text-dim)",
                                        textTransform: "uppercase",
                                        marginBottom: 12,
                                    }}
                                >
                                    {isCompositeView ? "Composite Risk Score · Cell-Level" : `${layerMeta.metric} · Cell-Level Severity`}
                                </div>
                                <div
                                    style={{
                                        fontFamily: "'Syne', sans-serif",
                                        fontSize: "3.5rem",
                                        fontWeight: 700,
                                        color: severityColor,
                                        lineHeight: 1,
                                        marginBottom: 8,
                                        textShadow: `0 0 30px ${severityColor}40`,
                                    }}
                                >
                                    {isCompositeView
                                        ? (zone.composite?.score == null ? "N/A" : Math.round(zone.composite.score))
                                        : activeTab === "aqi"
                                            ? (metrics.aqi == null ? "N/A" : Math.round(metrics.aqi))
                                            : activeTab === "lst"
                                                ? (metrics.lst !== null && metrics.lst !== undefined ? metrics.lst.toFixed(1) : "N/A")
                                                : activeTab === "water_health"
                                                    ? (metrics.water_health_score == null ? "N/A" : `${(metrics.water_health_score * 100).toFixed(0)}%`)
                                                    : (metrics[activeTab] == null ? "N/A" : metrics[activeTab].toFixed(2))}
                                </div>
                                <div
                                    style={{
                                        fontSize: "0.8rem",
                                        fontWeight: 600,
                                        letterSpacing: "0.15em",
                                        color: severityColor,
                                    }}
                                >
                                    {severityLabel}
                                </div>
                            </div>

                            {/* Definition & Bands */}
                            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
                                <div>
                                    <div style={{ fontSize: "0.6rem", color: "var(--cyan)", letterSpacing: "0.2em", marginBottom: 6 }}>METRIC DEFINITION</div>
                                    <div style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.8)", lineHeight: 1.5 }}>
                                        {layerMeta.definition}
                                    </div>
                                    <div style={{ fontSize: "0.7rem", color: "var(--text-dim)", marginTop: 6 }}>
                                        Method: {layerMeta.method}
                                    </div>
                                </div>

                                <div>
                                    <div style={{ fontSize: "0.6rem", color: "var(--cyan)", letterSpacing: "0.2em", marginBottom: 8 }}>CLASSIFICATION BANDS</div>
                                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                        {layerMeta.bands.map((band, i) => (
                                            <div
                                                key={i}
                                                style={{
                                                    padding: "4px 8px",
                                                    background: "rgba(255,255,255,0.03)",
                                                    border: "1px solid rgba(255,255,255,0.1)",
                                                    borderRadius: 4,
                                                    fontSize: "0.6rem",
                                                    letterSpacing: "0.05em",
                                                    color: "var(--text-dim)",
                                                }}
                                            >
                                                <span style={{ color: "white", marginRight: 4 }}>{band.range}</span>
                                                {band.label}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* 2. Isolation Forest Evidence (Replaces Trend) */}
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
                                <div style={{ width: 4, height: 16, background: "var(--cyan)" }} />
                                <div style={{ fontSize: "0.8rem", letterSpacing: "0.2em", color: "white", textTransform: "uppercase" }}>
                                    Environmental Intelligence Evidence
                                </div>
                            </div>

                            <div style={{
                                padding: "20px",
                                background: "rgba(0,0,0,0.3)",
                                border: "1px solid rgba(0,229,255,0.2)",
                                borderRadius: 8,
                                position: "relative",
                            }}>
                                <div style={{
                                    position: "absolute",
                                    top: 12,
                                    right: 16,
                                    fontSize: "0.5rem",
                                    color: "var(--cyan)",
                                    letterSpacing: "0.1em"
                                }}>
                                    SYSTEM MODEL
                                </div>

                                {explanationData ? (
                                    explanationData._unavailable ? (
                                        <div style={{ color: "var(--text-dim)", fontSize: "0.85rem", fontStyle: "italic" }}>
                                            Analysis unavailable for this location.
                                        </div>
                                    ) : (
                                        <div style={{
                                            color: "rgba(255,255,255,0.9)",
                                            fontSize: "0.85rem",
                                            lineHeight: 1.6,
                                            whiteSpace: "pre-wrap",
                                        }}>
                                            {getUserFacingExplanation(explanationData.deterministic_explanation)}
                                        </div>
                                    )
                                ) : (
                                    <div style={{ color: "var(--text-dim)", fontSize: "0.85rem" }}>
                                        Loading analytical evidence...
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* 3. Component Breakdown (Only for Composite) */}
                        {isCompositeView && (
                            <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
                                    <div style={{ width: 4, height: 16, background: "var(--cyan)" }} />
                                    <div style={{ fontSize: "0.8rem", letterSpacing: "0.2em", color: "white", textTransform: "uppercase" }}>
                                        Multi-Spectral Component Analysis
                                    </div>
                                </div>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                                    {metricCards.map((card) => (
                                        <div
                                            key={card.id}
                                            style={{
                                                padding: "16px",
                                                background: "rgba(255,255,255,0.02)",
                                                border: "1px solid rgba(255,255,255,0.05)",
                                                borderRadius: 8,
                                                display: "flex",
                                                flexDirection: "column",
                                            }}
                                        >
                                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                                                <span style={{ fontSize: "0.65rem", letterSpacing: "0.15em", color: "var(--text-dim)" }}>
                                                    {card.label}
                                                </span>
                                                <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.9rem", color: card.color }}>
                                                    {card.value}{card.unit}
                                                </span>
                                            </div>
                                            <div style={{ height: 4, background: "rgba(0,0,0,0.5)", borderRadius: 2, overflow: "hidden" }}>
                                                <div
                                                    style={{
                                                        height: "100%",
                                                        width: `${card.norm}%`,
                                                        background: card.color,
                                                    }}
                                                />
                                            </div>
                                            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: "0.55rem", color: "var(--text-dim)" }}>
                                                <span>Stress Contrib</span>
                                                <span>{Math.round(card.norm)}%</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Right Column (Contextual Drivers / Mitigation) */}
                    <div
                        style={{
                            flex: "0 0 40%",
                            background: "rgba(0,0,0,0.15)",
                            padding: "32px",
                            overflowY: "auto",
                            display: "flex",
                            flexDirection: "column",
                            gap: 32,
                        }}
                    >
                        {/* Static Context Warning */}
                        <div style={{
                            padding: "12px",
                            background: "rgba(255, 140, 0, 0.1)",
                            border: "1px solid rgba(255, 140, 0, 0.3)",
                            borderRadius: 6,
                            fontSize: "0.65rem",
                            color: "rgba(255, 140, 0, 0.9)",
                            lineHeight: 1.4,
                        }}>
                            <strong>STATIC CONTEXT:</strong> The drivers and mitigation strategies below are generalized contextual information for this zone, not dynamic model outputs.
                        </div>

                        {/* Location-Specific Data (if available) */}
                        {locationData ? (
                            <>
                                <div>
                                    <div style={{ fontSize: "0.7rem", color: "var(--text-dim)", letterSpacing: "0.2em", marginBottom: 16 }}>
                                        IDENTIFIED DRIVERS (CONTEXTUAL)
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                        {locationData.drivers.map((driver, idx) => (
                                            <div
                                                key={idx}
                                                style={{
                                                    display: "flex",
                                                    gap: 12,
                                                    alignItems: "flex-start",
                                                    padding: "12px 16px",
                                                    background: "rgba(255,255,255,0.03)",
                                                    borderLeft: "2px solid rgba(255,59,59,0.5)",
                                                    borderRadius: "0 6px 6px 0",
                                                }}
                                            >
                                                <div style={{ color: "rgba(255,59,59,0.8)", fontSize: "0.8rem", marginTop: -2 }}>
                                                    ⚠
                                                </div>
                                                <div style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.85)", lineHeight: 1.4 }}>
                                                    {driver}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div>
                                    <div style={{ fontSize: "0.7rem", color: "var(--text-dim)", letterSpacing: "0.2em", marginBottom: 16 }}>
                                        MITIGATION PATHWAYS (STATIC)
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                        {locationData.mitigation.map((mit, idx) => {
                                            const [timeframe, action] = mit.split(": ");
                                            return (
                                                <div
                                                    key={idx}
                                                    style={{
                                                        padding: "16px",
                                                        background: "rgba(0,229,255,0.03)",
                                                        border: "1px solid rgba(0,229,255,0.1)",
                                                        borderRadius: 8,
                                                    }}
                                                >
                                                    <div style={{ fontSize: "0.6rem", color: "var(--cyan)", letterSpacing: "0.15em", marginBottom: 6, textTransform: "uppercase" }}>
                                                        {timeframe}
                                                    </div>
                                                    <div style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.9)", lineHeight: 1.5 }}>
                                                        {action}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div style={{ color: "var(--text-dim)", fontSize: "0.85rem", fontStyle: "italic", textAlign: "center", marginTop: 40 }}>
                                No contextual location data available for {zone.name}.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

// ── Spatial Hierarchy Helpers ──────────────────────────────────────────────

function SpatialLevelHeader({ level, label, sublabel, accent }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <div
                style={{
                    width: 22,
                    height: 22,
                    borderRadius: "50%",
                    border: `1.5px solid ${accent}`,
                    background: `${accent}15`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.65rem",
                    fontWeight: 700,
                    color: accent,
                    textShadow: `0 0 8px ${accent}66`,
                    flexShrink: 0,
                }}
            >
                {level}
            </div>
            <div style={{ flex: 1 }}>
                <div
                    style={{
                        fontFamily: "'Syne', sans-serif",
                        fontSize: "0.7rem",
                        fontWeight: 600,
                        letterSpacing: "0.12em",
                        color: "rgba(255,255,255,0.88)",
                        textTransform: "uppercase",
                    }}
                >
                    {label}
                </div>
                {sublabel && (
                    <div
                        style={{
                            fontSize: "0.5rem",
                            letterSpacing: "0.08em",
                            color: "var(--text-dim)",
                            marginTop: 1,
                        }}
                    >
                        {sublabel}
                    </div>
                )}
            </div>
        </div>
    );
}

function MetricRow({ label, value, unit = "", color = "rgba(255,255,255,0.88)", nodata = false }) {
    const displayColor = nodata ? "rgba(255,255,255,0.32)" : color;
    return (
        <div>
            <div
                style={{
                    fontSize: "0.48rem",
                    letterSpacing: "0.14em",
                    color: "var(--text-dim)",
                    textTransform: "uppercase",
                    marginBottom: 2,
                }}
            >
                {label}
            </div>
            <div
                style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 3,
                }}
            >
                <span
                    style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: "0.82rem",
                        fontWeight: 500,
                        color: displayColor,
                        textShadow: nodata ? "none" : `0 0 8px ${color}44`,
                        opacity: nodata ? 0.6 : 1,
                    }}
                >
                    {value}
                </span>
                {unit && (
                    <span
                        style={{
                            fontFamily: "'DM Mono', monospace",
                            fontSize: "0.56rem",
                            fontWeight: 400,
                            color: displayColor,
                            opacity: nodata ? 0.5 : 0.7,
                        }}
                    >
                        {unit}
                    </span>
                )}
            </div>
        </div>
    );
}

function resolveActiveLayerId(activeLayers) {
    if (!activeLayers) return "aqi";
    if (activeLayers.all) return "composite";

    const selected = LAYER_PRIORITY.filter((layerId) => activeLayers[layerId]);
    if (selected.length > 1) return "composite";
    if (selected.length === 1) return selected[0];

    return "aqi";
}

const MUMBAI_LOCATIONS_DATA = {
    "Worli": {
        drivers: [
            "Vehicular emissions (45%)",
            "Coastal road construction dust (35%)",
            "High-rise building density (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy 3 mobile mist cannons at construction sites",
            "Short-term (1-3 months): Restrict truck entry 7am-9pm on Sea Link approach",
            "Long-term (3-12 months): Install green walls on all new high-rises"
        ]
    },
    "Bhakti Park/Wadala TT": {
        drivers: [
            "Cement mixing plant operations (50%)",
            "Metro line 4 construction (30%)",
            "Illegal waste burning in nullahs (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Shut down non-compliant cement plant",
            "Short-term (1-3 months): Install real-time AQI monitors at society gate",
            "Long-term (3-12 months): Convert 5 acres of wasteland to green buffer zone"
        ]
    },
    "Deonar": {
        drivers: [
            "Deonar dumping ground fires (55%)",
            "Industrial emissions (25%)",
            "Complete vegetation absence (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy 5 mist cannons + cover exposed waste",
            "Short-term (1-3 months): Install landfill gas capture system",
            "Long-term (3-12 months): Accelerate landfill closure + plant 10,000 trees"
        ]
    },
    "BKC": {
        drivers: [
            "Glass tower heat retention (40%)",
            "85% built-up / 5% green cover (35%)",
            "Vehicular congestion (25%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Mandate cool roofs on all commercial towers",
            "Short-term (1-3 months): Create pedestrian-only green corridors",
            "Long-term (3-12 months): Implement green roof mandate for all new buildings"
        ]
    },
    "Kurla": {
        drivers: [
            "Industrial zone emissions (40%)",
            "Slum redevelopment construction (35%)",
            "Mithi River pollution + waste burning (25%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Enforce construction dust control",
            "Short-term (1-3 months): Mandate green walls on industrial compounds",
            "Long-term (3-12 months): Create 5 neighborhood parks in open spaces"
        ]
    },
    "Sindhi Society": {
        drivers: [
            "Waste burning in nearby nullahs (45%)",
            "Encroaching construction (35%)",
            "Traffic congestion on connecting roads (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy air purifiers in nearby schools",
            "Short-term (1-3 months): Install CCTV to penalize waste burning",
            "Long-term (3-12 months): Create green buffer along nullah"
        ]
    },
    "Powai Lake": {
        drivers: [
            "Illegal encroachment on lake bed (40%)",
            "Reduced monsoon inflow -30% (35%)",
            "Siltation + surrounding construction (25%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Install aerators to prevent eutrophication",
            "Short-term (1-3 months): Remove encroachments within 100m buffer",
            "Long-term (3-12 months): Restore catchment area with native trees"
        ]
    },
    "Mithi River": {
        drivers: [
            "70% encroachment + concretization (50%)",
            "Solid waste dumping (30%)",
            "Siltation + sewage inflow (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Remove solid waste from 5 critical stretches",
            "Short-term (1-3 months): Demolish encroachments within 50m",
            "Long-term (3-12 months): Restore natural floodplain + plant mangroves"
        ]
    },
    "Thane Creek": {
        drivers: [
            "Industrial discharge (40%)",
            "Illegal dumping + construction (35%)",
            "Reduced freshwater inflow (25%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Declare conservation zone",
            "Short-term (1-3 months): Plant 50,000 mangrove saplings",
            "Long-term (3-12 months): Monitor water quality monthly + restrict discharge"
        ]
    },
    "Dharavi": {
        drivers: [
            "95% built-up / 0% green cover (50%)",
            "Metal roofing heat retention (30%)",
            "No open spaces or shade (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Install cool roofs on 100 community buildings",
            "Short-term (1-3 months): Create pocket parks in 5 open spaces",
            "Long-term (3-12 months): Mandate green cover in redevelopment plan"
        ]
    },
    "SGNP": {
        drivers: [
            "Protected forest status (60%)",
            "100+ sq km contiguous green cover (30%)",
            "Active conservation management (10%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Protect buffer zone from encroachment",
            "Short-term (1-3 months): Create green corridors to connect to city",
            "Long-term (3-12 months): Expand eco-sensitive zone by 2 km"
        ]
    },
    "Bandra (Khar Road)": {
        drivers: [
            "Construction site 200m east (50%)",
            "Waste transfer station 300m north (30%)",
            "Local traffic congestion (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Enforce dust control at specific construction site",
            "Short-term (1-3 months): Relocate waste transfer station",
            "Long-term (3-12 months): Create street-level green buffers"
        ]
    },
    "Mulund": {
        drivers: [
            "Eastern Expressway traffic (45%)",
            "Nearby industrial zones (35%)",
            "Ongoing infrastructure projects (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy dust suppression on Expressway",
            "Short-term (1-3 months): Plant trees along service roads",
            "Long-term (3-12 months): Create green buffer along industrial boundary"
        ]
    },
    "Bhandup": {
        drivers: [
            "Dense residential + no green space (50%)",
            "Nearby Thane industrial zone (30%)",
            "Local waste burning (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Identify and penalize waste burning spots",
            "Short-term (1-3 months): Create 3 neighborhood parks",
            "Long-term (3-12 months): Mandate rooftop gardens on new buildings"
        ]
    },
    "Nahur": {
        drivers: [
            "Residential + light industrial mix (45%)",
            "Mulund-Bhandup traffic corridor (35%)",
            "Lack of green infrastructure (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy mobile air quality monitor",
            "Short-term (1-3 months): Plant 500 trees along main road",
            "Long-term (3-12 months): Create linear park along railway line"
        ]
    },
    "Thane (Wagle Estate)": {
        drivers: [
            "Industrial zone - zero green cover (50%)",
            "Concrete + asphalt heat retention (30%)",
            "No tree plantation in 10+ years (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Mandate green walls on all factory compounds",
            "Short-term (1-3 months): Plant 500 trees along service roads",
            "Long-term (3-12 months): Green cover mandate for new industrial permits"
        ]
    },
    "Colaba": {
        drivers: [
            "Dense tourism + commercial activity (45%)",
            "Sea-facing heat reflection (35%)",
            "Limited green space (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Install street-level air purifiers",
            "Short-term (1-3 months): Create pedestrian-only green zones",
            "Long-term (3-12 months): Rooftop garden mandate for hotels"
        ]
    },
    "Borivali East": {
        drivers: [
            "Proximity to SGNP (60%)",
            "Residential with tree cover (30%)",
            "Lower industrial activity (10%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Maintain current green cover",
            "Short-term (1-3 months): Protect existing tree population",
            "Long-term (3-12 months): Expand green corridors toward SGNP"
        ]
    },
    "Andheri": {
        drivers: [
            "Western Expressway traffic (50%)",
            "Airport emissions (30%)",
            "High density + limited parks (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Deploy mist cannons along Expressway",
            "Short-term (1-3 months): Create green buffers along service roads",
            "Long-term (3-12 months): Mandate EV charging + tree plantation"
        ]
    },
    "Navi Mumbai": {
        drivers: [
            "Planned city but growing construction (50%)",
            "Industrial pockets (30%)",
            "Mangrove proximity - protection needed (20%)"
        ],
        mitigation: [
            "Immediate (0-7 days): Enforce dust control at construction sites",
            "Short-term (1-3 months): Protect mangrove buffer zones",
            "Long-term (3-12 months): Expand planned green spaces"
        ]
    }
};

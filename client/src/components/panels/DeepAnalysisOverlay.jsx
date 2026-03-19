import { memo, useEffect, useMemo, useState } from "react";
import { getAqiCpcbBand, getLstBand, getNdviBand, getNdwiBand, getSeverityColor, getSeverityLabel, getZoneMetrics, getMetricDisplay, normalizeMetric } from "../../utils/helpers";
import TrendSparkline from "../ui/TrendSparkline";
import RootCauseBar from "../ui/RootCauseBar";

const LAYER_PRIORITY = ["aqi", "ndvi", "ndwi", "lst"];
const COMPOSITE_ACCENT_COLOR = "#b45309";

const LAYER_META = {
    composite: { icon: "⬡", label: "Composite", color: COMPOSITE_ACCENT_COLOR },
    aqi: { icon: "○", label: "AQI", color: "#ff8c00" },
    ndvi: { icon: "◇", label: "NDVI", color: "#1dd1a1" },
    ndwi: { icon: "◈", label: "NDWI", color: "#00b4d8" },
    lst: { icon: "▣", label: "LST", color: "#ff5f57" },
};

const ANALYSIS_MODE_ORDER = ["composite", "aqi", "ndvi", "ndwi", "lst"];

const LAYER_REFERENCE = {
    composite: {
        metric: "Composite Risk Score (0-100)",
        definition: "Aggregated anomaly severity combining AQI, NDVI, NDWI and LST stress signals.",
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
    ndwi: {
        metric: "NDWI (-1 to 1)",
        definition: "Normalized Difference Water Index used here as a water-condition anomaly indicator.",
        method: "(Green - NIR) / (Green + NIR)",
        bands: [
            { range: "< -0.10", label: "VERY LOW MOISTURE" },
            { range: "-0.10-0.04", label: "LOW MOISTURE" },
            { range: "0.05-0.19", label: "MODERATE MOISTURE" },
            { range: "0.20-0.34", label: "HIGH MOISTURE" },
            { range: ">= 0.35", label: "VERY HIGH MOISTURE" },
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

function resolveActiveLayerId(activeLayers) {
    if (!activeLayers) return "aqi";
    if (activeLayers.all) return "composite";

    const selected = LAYER_PRIORITY.filter((layerId) => activeLayers[layerId]);
    if (selected.length > 1) return "composite";
    if (selected.length === 1) return selected[0];

    return "aqi";
}

function strongestFactor(metrics) {
    const factors = [
        { key: "aqi", label: "AQI", value: normalizeMetric("aqi", metrics) },
        { key: "ndvi", label: "NDVI", value: normalizeMetric("ndvi", metrics) },
        { key: "ndwi", label: "NDWI", value: normalizeMetric("ndwi", metrics) },
        { key: "lst", label: "LST", value: normalizeMetric("lst", metrics) },
    ];

    return factors.sort((a, b) => b.value - a.value)[0];
}

function zoneContextTags(zoneName) {
    const name = zoneName.toLowerCase();
    return {
        traffic: /corridor|hub|estate|sector|layout|vihar|kurla/.test(name),
        industrial: /industrial|petrochemical|complex|cluster|belt/.test(name),
        landfill: /landfill|waste|ghazipur/.test(name),
        waterbody: /lake|creek|floodplain|yamuna|estuary|wetland|basin|catchment/.test(name),
    };
}

function inferLikelyDrivers(zone, metrics) {
    const tags = zoneContextTags(zone.name);
    const drivers = [];

    if (metrics.aqi >= 250) {
        drivers.push("CPCB AQI spike is likely linked to elevated combustion pollutants (CO/NOx/PM2.5), indicating strong aerosol load in the air column.");
        if (tags.traffic) {
            drivers.push("Location pattern suggests traffic corridor contribution: sustained vehicle density can raise near-surface CO and particulate concentration.");
        }
        if (tags.industrial) {
            drivers.push("Industrial adjacency may be amplifying stack/process emissions, which can intensify local haze and secondary aerosol formation.");
        }
        if (tags.landfill) {
            drivers.push("Waste/landfill influence can elevate methane-burning episodes and fugitive emissions, adding to PM and toxic plume burden.");
        }
    } else if (metrics.aqi >= 160) {
        drivers.push("Moderate-to-high CPCB AQI suggests mixed-source pollution, likely from traffic combustion plus local dust/aerosol recirculation.");
    }

    if (metrics.ndwi >= 0.35) {
        drivers.push("Water stress is high: probable contamination or stagnant-flow conditions, consistent with sewage/industrial runoff loading near waterways.");
        if (tags.waterbody) {
            drivers.push("Hydrological context (lake/creek/floodplain) indicates poor flushing can trap pollutants and elevate surface-water anomaly intensity.");
        }
    }

    if (metrics.ndvi <= 0.12) {
        drivers.push("Low NDVI indicates weak vegetation cover, reducing natural cooling and pollutant buffering capacity.");
    }

    if (metrics.lst >= 38) {
        drivers.push("Elevated LST indicates surface heat buildup, which can intensify ozone chemistry and trap pollution near ground level.");
    }

    if (metrics.aqi >= 180 && metrics.lst >= 36) {
        drivers.push("Cross-factor signal: high CPCB AQI + high LST suggests thermal stagnation is reinforcing aerosol persistence.");
    }

    if (drivers.length === 0) {
        drivers.push("Current anomaly appears multi-factor but moderate; monitor trend continuation before confirming a dominant physical driver.");
    }

    return drivers;
}

function inferLayerDrivers(layerId, zone, metrics) {
    switch (layerId) {
        case "aqi": {
            if (metrics.aqi >= 250) {
                return [
                    "AQI is in severe range, indicating strong particulate and combustion-gas loading in the zone.",
                    "Traffic and industrial plume carryover are likely amplifying near-surface pollution concentration.",
                ];
            }
            if (metrics.aqi >= 160) {
                return [
                    "AQI indicates moderate-to-high stress, likely from mixed urban combustion sources.",
                ];
            }
            return ["AQI is currently moderate; monitor trend persistence before confirming a dominant emission source."];
        }

        case "ndvi": {
            if (metrics.ndvi <= 0.12) {
                return [
                    "Low NDVI reflects weak vegetative cover, reducing natural pollutant buffering and surface cooling.",
                    "Sparse green cover can amplify local heat retention and ecological stress response.",
                ];
            }
            return ["NDVI remains relatively stable; no acute vegetation stress signal is dominant right now."];
        }

        case "ndwi": {
            if (metrics.ndwi >= 0.35) {
                return [
                    "NDWI indicates high water anomaly pressure, consistent with contamination/stagnation stress.",
                    "Hydrological retention effects may be concentrating runoff-related pollutants in this zone.",
                ];
            }
            return ["NDWI signal is moderate; water-system stress is present but not at critical anomaly levels."];
        }

        case "lst": {
            if (metrics.lst >= 38) {
                return [
                    "LST is elevated, indicating strong surface heat accumulation and urban heat-island behavior.",
                    "Thermal buildup can intensify atmospheric stagnation and worsen environmental stress outcomes.",
                ];
            }
            return ["LST is controlled relative to peak-risk thresholds; heat stress is present but not extreme."];
        }

        case "composite":
        default:
            return [
                `Composite signal remains elevated for ${zone.name}; cross-metric coupling is driving the zone-level risk pattern.`,
            ];
    }
}

function inferMitigationActions(layerId, zone, metrics) {
    switch (layerId) {
        case "aqi":
            return [
                "Enforce traffic emission controls on peak corridors and increase public-transport share during high AQI windows.",
                "Strengthen industrial stack monitoring and temporary curbs during poor/very-poor episodes.",
                "Deploy dust suppression and construction-site containment in nearby hotspots.",
            ];

        case "ndvi":
            return [
                "Increase native urban green cover (roadside canopy, pocket forests, and riparian planting).",
                "Protect existing vegetated patches from land-use conversion and improve soil moisture retention.",
                "Prioritize low-NDVI grids for seasonal restoration and canopy continuity planning.",
            ];

        case "ndwi":
            return [
                "Improve wastewater interception and treatment before discharge into lakes/creeks/drains.",
                "Restore waterbody circulation and remove stagnation pockets through desilting and flow management.",
                "Control runoff pollution with stormwater filtration and buffer wetlands.",
            ];

        case "lst":
            return [
                "Reduce heat-island load using cool roofs, high-albedo surfaces, and shaded streets.",
                "Expand tree canopy in high-LST sectors and protect evapotranspiration corridors.",
                "Limit thermal emissions from dense built-up clusters during peak heat periods.",
            ];

        case "composite":
        default:
            return [
                "Run an integrated plan combining emission control, water-quality restoration, and heat-island reduction.",
                "Target top anomaly grids first using weekly CPCB AQI, NDVI, NDWI, and LST tracking.",
                "Set zone-specific reduction targets and trigger interventions when risk bands escalate.",
            ];
    }
}

function getTrendYAxisTicks(data) {
    if (!data || data.length === 0) return [];
    const max = Math.max(...data);
    const min = Math.min(...data);
    const mid = (max + min) / 2;

    return [max, mid, min];
}

function formatTrendTick(value, layerId) {
    const normalized = Math.max(0, Math.min(100, Number(value) || 0));

    if (layerId === "composite") return `${Math.round(normalized)}%`;
    if (layerId === "aqi") return `${Math.round((normalized / 100) * 500)}`;
    if (layerId === "ndvi") return `${(-0.2 + (normalized / 100) * 1.0).toFixed(2)}`;
    if (layerId === "ndwi") return `${(-0.3 + (normalized / 100) * 0.9).toFixed(2)}`;
    if (layerId === "lst") return `${Math.round(24 + (normalized / 100) * 23)}°C`;

    return `${Math.round(normalized)}`;
}

function getTrendAxisLaneWidth(layerId) {
    return 38;
}

function DeepAnalysisOverlay({ zone, cityLabel, trendData, activeLayers, isOpen, onClose }) {
    const defaultMode = useMemo(() => resolveActiveLayerId(activeLayers), [activeLayers]);
    const [viewMode, setViewMode] = useState(defaultMode);

    useEffect(() => {
        if (isOpen) {
            setViewMode(defaultMode);
        }
    }, [isOpen, defaultMode, zone?.name]);

    if (!isOpen || !zone) return null;

    const metrics = getZoneMetrics(zone);
    const isCompositeView = viewMode === "composite";
    const focusLayerId = viewMode;
    const focusMeta = LAYER_META[focusLayerId] || LAYER_META.aqi;
    const accentColor = focusMeta.color;
    const factor = isCompositeView
        ? strongestFactor(metrics)
        : { label: focusMeta.label };
    const likelyDrivers = isCompositeView
        ? inferLikelyDrivers(zone, metrics)
        : inferLayerDrivers(focusLayerId, zone, metrics);
    const mitigationActions = inferMitigationActions(focusLayerId, zone, metrics);
    const yAxisTicks = getTrendYAxisTicks(trendData);
    const yAxisLaneWidth = getTrendAxisLaneWidth(focusLayerId);

    const isFocusedComposite = focusLayerId === "composite";
    const focusedMetricLabel = isFocusedComposite ? "Composite Risk Score" : focusMeta.label;
    const focusedMetricValue = isFocusedComposite
        ? zone.severity.toFixed(1)
        : getMetricDisplay(focusLayerId, metrics);
    const focusedMetricNormalized = isFocusedComposite
        ? zone.severity
        : normalizeMetric(focusLayerId, metrics);
    const headerSeverityScore = isCompositeView ? zone.severity : focusedMetricNormalized;
    const headerSeverityLabel = (() => {
        if (focusLayerId === "aqi") return getAqiCpcbBand(metrics?.aqi);
        if (focusLayerId === "ndvi") return getNdviBand(metrics?.ndvi);
        if (focusLayerId === "ndwi") return getNdwiBand(metrics?.ndwi);
        if (focusLayerId === "lst") return getLstBand(metrics?.lst);
        return getSeverityLabel(headerSeverityScore);
    })();
    const headerSeverityColor = getSeverityColor(headerSeverityScore);
    const headerSeverityScope = focusLayerId === "aqi" ? "CPCB AQI" : focusMeta.label;
    const zoneDisplayName = cityLabel ? `${zone.name}, ${cityLabel}` : zone.name;

    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 120,
                background: "rgba(4, 8, 12, 0.9)",
                backdropFilter: "blur(8px)",
                WebkitBackdropFilter: "blur(8px)",
                padding: "22px",
                overflowY: "auto",
            }}
        >
            <div
                className="glass"
                style={{
                    width: "100%",
                    minHeight: "calc(100vh - 44px)",
                    borderRadius: 14,
                    padding: "20px 22px",
                    border: "1px solid rgba(0,229,255,0.16)",
                }}
            >
                <div
                    style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        gap: 20,
                        marginBottom: 16,
                    }}
                >
                    <div>
                        <div
                            style={{
                                fontSize: "0.62rem",
                                letterSpacing: "0.2em",
                                color: "rgba(0,229,255,0.55)",
                                textTransform: "uppercase",
                                marginBottom: 8,
                            }}
                        >
                            Deep Analysis
                        </div>
                        <div
                            style={{
                                fontFamily: "'Syne', sans-serif",
                                fontSize: "1.35rem",
                                fontWeight: 700,
                                color: "rgba(255,255,255,0.94)",
                                letterSpacing: "0.04em",
                                lineHeight: 1.35,
                                paddingBottom: 2,
                            }}
                        >
                            {zoneDisplayName}
                        </div>
                        <div
                            style={{
                                marginTop: 7,
                                fontSize: "0.64rem",
                                color: "var(--text-dim)",
                                letterSpacing: "0.11em",
                            }}
                        >
                            {zone.coords[1].toFixed(4)}°N {zone.coords[0].toFixed(4)}°E  ·  SEVERITY ({headerSeverityScope.toUpperCase()}) <span style={{ color: headerSeverityColor }}>{headerSeverityLabel}</span>
                        </div>

                        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                            {ANALYSIS_MODE_ORDER.map((modeId) => (
                                <ViewChip
                                    key={modeId}
                                    label={LAYER_META[modeId].label}
                                    active={viewMode === modeId}
                                    activeColor={LAYER_META[modeId].color}
                                    onClick={() => setViewMode(modeId)}
                                />
                            ))}
                        </div>
                    </div>

                    <button
                        onClick={onClose}
                        style={{
                            background: "transparent",
                            border: "1px solid rgba(0,229,255,0.24)",
                            color: "rgba(0,229,255,0.88)",
                            borderRadius: 8,
                            padding: "9px 14px",
                            fontSize: "0.62rem",
                            letterSpacing: "0.14em",
                            textTransform: "uppercase",
                            cursor: "pointer",
                        }}
                    >
                        Close
                    </button>
                </div>

                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns: isCompositeView ? "repeat(5, minmax(0, 1fr))" : "repeat(2, minmax(0, 1fr))",
                        gap: 12,
                        marginBottom: 16,
                    }}
                >
                    {isCompositeView ? (
                        <>
                            <MetricCard label="Composite Risk Score" value={zone.severity.toFixed(1)} valueColor={COMPOSITE_ACCENT_COLOR} />
                            <MetricCard label="CPCB AQI" value={getMetricDisplay("aqi", metrics)} valueColor={LAYER_META.aqi.color} />
                            <MetricCard label="NDVI" value={getMetricDisplay("ndvi", metrics)} valueColor={LAYER_META.ndvi.color} />
                            <MetricCard label="NDWI" value={getMetricDisplay("ndwi", metrics)} valueColor={LAYER_META.ndwi.color} />
                            <MetricCard label="LST" value={getMetricDisplay("lst", metrics)} valueColor={LAYER_META.lst.color} />
                        </>
                    ) : (
                        <>
                            <MetricCard label={focusedMetricLabel} value={focusedMetricValue} valueColor={accentColor} />
                            <MetricCard label={`${focusMeta.label} Intensity`} value={`${Math.round(focusedMetricNormalized)}%`} valueColor={accentColor} />
                        </>
                    )}
                </div>

                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns: "1.1fr 1.2fr",
                        gap: 16,
                        alignItems: "start",
                    }}
                >
                    <div className="glass" style={{ padding: 14, borderRadius: 10 }}>
                        <SectionLabel>{isCompositeView ? "Composite Legend" : `${focusMeta.label} Legend`}</SectionLabel>
                        <LayerLegendCard
                            layerId={focusLayerId}
                            meta={focusMeta}
                            details={LAYER_REFERENCE[focusLayerId]}
                            active
                        />
                    </div>

                    <div className="glass" style={{ padding: 14, borderRadius: 10 }}>
                        <SectionLabel>{isCompositeView ? "14-Day Trend (Expanded)" : `14-Day ${focusMeta.label} Trend`}</SectionLabel>
                        <div
                            style={{
                                height: 170,
                                borderBottom: "1px solid rgba(0,229,255,0.16)",
                                position: "relative",
                                marginBottom: 8,
                                display: "flex",
                            }}
                        >
                            <div
                                style={{
                                    width: yAxisLaneWidth,
                                    display: "flex",
                                    flexDirection: "column",
                                    justifyContent: "space-between",
                                    alignItems: "flex-end",
                                    paddingRight: 4,
                                    paddingTop: 2,
                                    paddingBottom: 2,
                                    flexShrink: 0,
                                }}
                            >
                                {yAxisTicks.map((tick) => (
                                    <span
                                        key={tick}
                                        style={{
                                            fontSize: "0.56rem",
                                            color: "rgba(200,214,229,0.48)",
                                            letterSpacing: "0.04em",
                                            lineHeight: 1.05,
                                            whiteSpace: "nowrap",
                                            fontFamily: "'DM Mono', monospace",
                                            fontVariantNumeric: "tabular-nums",
                                            fontWeight: 500,
                                        }}
                                    >
                                        {formatTrendTick(tick, focusLayerId)}
                                    </span>
                                ))}
                            </div>
                            <div style={{ flex: 1, minWidth: 0, borderLeft: "1px solid rgba(0,229,255,0.16)" }}>
                                <TrendSparkline data={trendData} color={accentColor} />
                            </div>
                        </div>
                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                fontSize: "0.52rem",
                                color: "rgba(200,214,229,0.33)",
                                letterSpacing: "0.1em",
                            }}
                        >
                            <span>14D AGO</span>
                            <span>ANOMALY TRAJECTORY</span>
                            <span>NOW</span>
                        </div>
                    </div>
                </div>

                <div className="glass" style={{ marginTop: 16, padding: 14, borderRadius: 10 }}>
                    <SectionLabel>{isCompositeView ? "Root Cause Breakdown" : `${focusMeta.label} Breakdown`}</SectionLabel>
                    {isCompositeView ? (
                        <>
                            <RootCauseBar
                                icon="○"
                                label="AQI"
                                value={metrics.aqi}
                                normalizedValue={normalizeMetric("aqi", metrics)}
                                displayValue={getMetricDisplay("aqi", metrics)}
                                color="#ff8c00"
                            />
                            <RootCauseBar
                                icon="◇"
                                label="NDVI"
                                value={metrics.ndvi}
                                normalizedValue={normalizeMetric("ndvi", metrics)}
                                displayValue={getMetricDisplay("ndvi", metrics)}
                                color="#1dd1a1"
                            />
                            <RootCauseBar
                                icon="◈"
                                label="NDWI"
                                value={metrics.ndwi}
                                normalizedValue={normalizeMetric("ndwi", metrics)}
                                displayValue={getMetricDisplay("ndwi", metrics)}
                                color="#00b4d8"
                            />
                            <RootCauseBar
                                icon="▣"
                                label="LST"
                                value={metrics.lst}
                                normalizedValue={normalizeMetric("lst", metrics)}
                                displayValue={getMetricDisplay("lst", metrics)}
                                color="#ff5f57"
                            />
                        </>
                    ) : (
                        <RootCauseBar
                            icon={focusMeta.icon}
                            label={focusMeta.label}
                            value={isFocusedComposite ? zone.severity : metrics[focusLayerId]}
                            normalizedValue={focusedMetricNormalized}
                            displayValue={focusedMetricValue}
                            color={accentColor}
                        />
                    )}

                    <div style={{ marginTop: 14, fontSize: "0.62rem", color: "var(--text)", letterSpacing: "0.07em" }}>
                        Primary driver: <span style={{ color: accentColor }}>{factor.label.toUpperCase()}</span>
                    </div>

                    <div
                        style={{
                            marginTop: 14,
                            paddingTop: 10,
                            borderTop: "1px solid rgba(0,229,255,0.12)",
                        }}
                    >
                        <SectionLabel>Likely Drivers</SectionLabel>
                        <ul style={{ listStyle: "none", display: "grid", gap: 8 }}>
                            {likelyDrivers.map((text) => (
                                <li
                                    key={text}
                                    style={{
                                        fontSize: "0.62rem",
                                        color: "var(--text)",
                                        letterSpacing: "0.04em",
                                        lineHeight: 1.5,
                                        paddingLeft: 12,
                                        position: "relative",
                                    }}
                                >
                                    <span
                                        style={{
                                            position: "absolute",
                                            left: 0,
                                            top: 0,
                                            color: "rgba(0,229,255,0.72)",
                                        }}
                                    >
                                        •
                                    </span>
                                    {text}
                                </li>
                            ))}
                        </ul>
                    </div>

                    <div
                        style={{
                            marginTop: 14,
                            paddingTop: 10,
                            borderTop: "1px solid rgba(0,229,255,0.12)",
                        }}
                    >
                        <SectionLabel>Mitigation Actions</SectionLabel>
                        <ul style={{ listStyle: "none", display: "grid", gap: 8 }}>
                            {mitigationActions.map((text) => (
                                <li
                                    key={text}
                                    style={{
                                        fontSize: "0.62rem",
                                        color: "var(--text)",
                                        letterSpacing: "0.04em",
                                        lineHeight: 1.5,
                                        paddingLeft: 12,
                                        position: "relative",
                                    }}
                                >
                                    <span
                                        style={{
                                            position: "absolute",
                                            left: 0,
                                            top: 0,
                                            color: "rgba(0,229,255,0.72)",
                                        }}
                                    >
                                        •
                                    </span>
                                    {text}
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}

function areSameActiveLayers(prevLayers, nextLayers) {
    if (prevLayers === nextLayers) return true;
    if (!prevLayers || !nextLayers) return false;

    return (
        prevLayers.aqi === nextLayers.aqi &&
        prevLayers.ndvi === nextLayers.ndvi &&
        prevLayers.ndwi === nextLayers.ndwi &&
        prevLayers.lst === nextLayers.lst &&
        prevLayers.all === nextLayers.all
    );
}

function areDeepAnalysisPropsEqual(prevProps, nextProps) {
    if (prevProps.isOpen !== nextProps.isOpen) return false;
    if (prevProps.zone !== nextProps.zone) return false;
    if (prevProps.trendData !== nextProps.trendData) return false;
    if (!areSameActiveLayers(prevProps.activeLayers, nextProps.activeLayers)) return false;

    return true;
}

export default memo(DeepAnalysisOverlay, areDeepAnalysisPropsEqual);

function ViewChip({ label, active, activeColor, onClick }) {
    return (
        <button
            onClick={onClick}
            style={{
                border: active ? `1px solid ${activeColor}88` : "1px solid rgba(0,229,255,0.18)",
                background: active ? `${activeColor}22` : "rgba(11,15,20,0.55)",
                color: active ? activeColor : "var(--text-dim)",
                borderRadius: 7,
                padding: "6px 10px",
                cursor: "pointer",
                fontSize: "0.54rem",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                fontFamily: "'DM Mono', monospace",
                transition: "all 0.2s ease",
            }}
        >
            {label}
        </button>
    );
}

function LayerLegendCard({ layerId, meta, details, active }) {
    return (
        <div
            className="glass"
            style={{
                borderRadius: 8,
                padding: "11px 12px",
                border: active ? `1px solid ${meta.color}66` : "1px solid rgba(0,229,255,0.14)",
                boxShadow: active ? `0 0 16px ${meta.color}22` : "none",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
                <span style={{ fontSize: "0.68rem", color: meta.color }}>{meta.icon}</span>
                <span
                    style={{
                        fontSize: "0.6rem",
                        letterSpacing: "0.12em",
                        color: meta.color,
                        textTransform: "uppercase",
                        fontFamily: "'DM Mono', monospace",
                    }}
                >
                    {meta.label}
                </span>
            </div>

            <div style={{ fontSize: "0.58rem", color: "var(--text)", letterSpacing: "0.04em", lineHeight: 1.45 }}>
                <div style={{ color: "var(--text-dim)", marginBottom: 4 }}>Metric: {details.metric}</div>
                <div style={{ marginBottom: 4 }}>{details.definition}</div>
                <div style={{ color: "var(--text-dim)", marginBottom: 6 }}>Method: {details.method}</div>

                <div style={{ color: "var(--text-dim)", marginBottom: 4, letterSpacing: "0.08em", textTransform: "uppercase", fontSize: "0.54rem" }}>
                    Bands
                </div>
                <div style={{ display: "grid", gap: 2 }}>
                    {details.bands.map((band) => (
                        <div key={`${layerId}-${band.range}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, lineHeight: 1.35 }}>
                            <span style={{ color: "rgba(200,214,229,0.8)" }}>{band.range}</span>
                            <span style={{ color: "var(--text-dim)", textAlign: "right" }}>{band.label}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function MetricCard({ label, value, valueColor = "var(--cyan)" }) {
    return (
        <div className="glass" style={{ padding: "10px 12px", borderRadius: 9 }}>
            <div style={{ fontSize: "0.52rem", color: "var(--text-dim)", letterSpacing: "0.12em", textTransform: "uppercase" }}>
                {label}
            </div>
            <div
                style={{
                    marginTop: 5,
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "1.12rem",
                    color: valueColor,
                    fontWeight: 600,
                    letterSpacing: "-0.02em",
                }}
            >
                {value}
            </div>
        </div>
    );
}

function SectionLabel({ children }) {
    return (
        <div
            style={{
                fontSize: "0.58rem",
                letterSpacing: "0.2em",
                color: "var(--text-dim)",
                textTransform: "uppercase",
                marginBottom: 12,
            }}
        >
            {children}
        </div>
    );
}

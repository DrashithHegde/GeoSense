import { useEffect, useRef, useState } from "react";
import ProvenanceBadge, { provFor } from "./ProvenanceBadge";
import { CLASS_STYLE } from "./AIInsightSection";
import SeasonChart from "./SeasonChart";
import ModelsPanel from "./ModelsPanel";
import { Ask, Card, Factors, Mitigation, ModelCheck, Muted, Relationships, Section, Sources, SummaryBlock, SupportingMeasures, TimeOrder, hasRelationships, hasTimeOrder } from "./DeepAnalysisSections";
import { waterBandFromPercentile, waterPercentileFromExplanation } from "../../utils/helpers";
import { getAqiCpcbBand, getLstBand, getNdviBand, getSeverityColor, getZoneMetrics, normalizeMetric } from "../../utils/helpers";

// ─────────────────────────────────────────────────────────────────────────────
// DeepAnalysisOverlay
// Tabs: Composite · AQI · NDVI · Water Health · LST · Models & accuracy. It opens on the layer
// shown on the map. A layer tab shows ONLY that layer; Composite shows every layer.
// One column: at a glance → what the data shows → (composite breakdown) → over time →
// why it might be like this → what would help → model check → ask → sources & limits.
// "Models & accuracy" shows the city-wide model results (ModelsPanel.jsx).
// ─────────────────────────────────────────────────────────────────────────────

const LAYER_PRIORITY = ["aqi", "ndvi", "water_health", "lst"];

const FOCUS_META = {
    composite: { icon: "⬡", tab: "Composite", label: "Composite · all layers", short: "Composite stress", color: "#ff5d73" },
    aqi: { icon: "○", tab: "AQI", label: "Air Quality Index (AQI)", short: "AQI", color: "#ffb347" },
    ndvi: { icon: "◇", tab: "NDVI", label: "Vegetation · NDVI", short: "NDVI", color: "#1dd1a1" },
    water_health: { icon: "◈", tab: "Water Health", label: "Water Health", short: "Water Health", color: "#2ec5ff" },
    lst: { icon: "▣", tab: "LST", label: "Surface heat · LST", short: "LST", color: "#ff6a3d" },
    models: { icon: "▤", tab: "Models & accuracy", label: "Models & accuracy", short: "Models", color: "#7ad7ff" },
};
const TAB_ORDER = ["composite", "aqi", "ndvi", "water_health", "lst", "models"];

const LAYER_REFERENCE = {
    composite: {
        metric: "Composite stress (0–100)",
        definition: "GeoSense-derived index (not an official one) combining surface heat, surface condition (vegetation deficit on land, Water Health deficit on water) and air quality. Each part is scaled 0 (least concern) to 1 (most) across the study region; the score is shown ×100.",
        method: "Weights 0.40 heat / 0.35 surface / 0.25 air, renormalised over the parts present; needs at least 2 of 3. Missing parts are never counted as zero.",
        bands: [
            { range: "0–24", label: "LOW" },
            { range: "25–49", label: "MODERATE" },
            { range: "50–69", label: "HIGH" },
            { range: "70–84", label: "SEVERE" },
            { range: "85–100", label: "CRITICAL" },
        ],
    },
    aqi: {
        metric: "Air Quality Index, AQI (0–500, India's CPCB scale)",
        definition: "India's National Air Quality Index from official CPCB-network monitoring stations (readings at most 48 h old). Between stations the value is interpolated, so it is an estimate.",
        method: "CPCB sub-index breakpoints; the AQI is the highest pollutant sub-index",
        bands: [
            { range: "0–50", label: "GOOD" },
            { range: "51–100", label: "SATISFACTORY" },
            { range: "101–200", label: "MODERATE" },
            { range: "201–300", label: "POOR" },
            { range: "301–400", label: "VERY POOR" },
            { range: "401–500", label: "SEVERE" },
        ],
    },
    ndvi: {
        metric: "NDVI (−1 to 1)",
        definition: "Normalized Difference Vegetation Index from Sentinel-2 (10 m): how much healthy green vegetation the surface has.",
        method: "(NIR − Red) / (NIR + Red), cloud-masked median over the period",
        bands: [
            { range: "< 0.00", label: "WATER / WET" },
            { range: "0.00–0.19", label: "BARE OR BUILT-UP" },
            { range: "0.20–0.39", label: "SPARSE" },
            { range: "0.40–0.59", label: "MODERATE" },
            { range: "≥ 0.60", label: "DENSE" },
        ],
    },
    water_health: {
        metric: "Water Health index (0–1)",
        definition: "Satellite water-condition proxy, computed only where MNDWI detects water. Bands are relative to all water cells in the study region — not a lab measurement.",
        method: "Algal-related (NDCI) and suspended-material (turbidity) spectral proxies",
        bands: [
            { range: "top 30% of water cells", label: "BETTER THAN MOST" },
            { range: "30–70%", label: "TYPICAL" },
            { range: "10–30%", label: "WATCH" },
            { range: "bottom 10%", label: "POTENTIAL CONCERN" },
        ],
    },
    lst: {
        metric: "Land surface temperature (°C)",
        definition: "How hot the ground and roofs are, from Landsat 8/9 thermal data (30 m). Surface temperature is not air temperature: roofs and roads can be 10–20 °C hotter than the air.",
        method: "Landsat Collection 2 Level-2 surface temperature, cloud-masked",
        bands: [
            { range: "< 28 °C", label: "COOL" },
            { range: "28–31.9 °C", label: "MILD" },
            { range: "32–35.9 °C", label: "WARM" },
            { range: "36–39.9 °C", label: "HOT" },
            { range: "≥ 40 °C", label: "EXTREME" },
        ],
    },
};

function compositeBand(score) {
    if (score == null) return "N/A";
    if (score >= 85) return "CRITICAL";
    if (score >= 70) return "SEVERE";
    if (score >= 50) return "HIGH";
    if (score >= 25) return "MODERATE";
    return "LOW";
}

function compositeColor(score) {
    if (score == null) return "rgba(255,255,255,0.5)";
    if (score >= 85) return "#ff3b3b";
    if (score >= 70) return "#ff5f57";
    if (score >= 50) return "#ff8c00";
    if (score >= 25) return "#ffd23c";
    return "#1dd1a1";
}

const fmt = (v, d) => (v == null || Number.isNaN(Number(v)) ? null : Number(v).toFixed(d));

// ─────────────────────────────────────────────────────────────────────────────

export default function DeepAnalysisOverlay({
    zone,
    pointAnalysis,
    cityLabel,
    explanationData,
    explanationLoading = false,
    aiPending = false,
    activeLayers,
    isOpen,
    onClose,
    onFocusChange = null,
    provenance = null,
    mlSummary = null,
}) {
    const mapFocus = resolveActiveLayerId(activeLayers);
    // tab = the layer being read in Deep Analysis: the map's layer unless the user picked a tab.
    // (Syncing it in an effect let the first render after opening use the layer from when the app
    // started, which fetched that layer's evidence first and then reloaded the right one.)
    const [pickedTab, setTab] = useState(null);
    const tab = pickedTab ?? mapFocus;
    useEffect(() => {
        if (!isOpen) setTab(null);
    }, [isOpen]);
    useEffect(() => {
        setTab(null);       // the map's layer changed: follow it
    }, [mapFocus]);
    const isModels = tab === "models";
    const focus = isModels ? null : tab;

    // Once per tab (and per location): that layer's evidence, then its AI summary.
    const requestedRef = useRef(null);
    const pointKey = `${pointAnalysis?.location?.longitude}|${pointAnalysis?.location?.latitude}`;
    useEffect(() => {
        if (!isOpen) {
            requestedRef.current = null;
            return;
        }
        if (!onFocusChange || !focus) return;
        const key = `${pointKey}|${focus}`;
        if (requestedRef.current === key) return;
        requestedRef.current = key;
        if (explanationData?.focus !== focus || explanationData?.llm_requested === false) onFocusChange(focus);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen, focus, pointKey]);

    // Esc closes
    useEffect(() => {
        if (!isOpen) return;
        const onKey = (e) => e.key === "Escape" && onClose?.();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [isOpen, onClose]);

    // scroll back to the top when the tab changes
    const bodyRef = useRef(null);
    useEffect(() => {
        if (bodyRef.current) bodyRef.current.scrollTop = 0;
    }, [tab]);

    const metrics = zone ? getZoneMetrics(zone) : null;
    if (!zone || !metrics) return null;

    const pixel = pointAnalysis?.pixel || zone?.pointAnalysis?.pixel || null;
    const cell = pointAnalysis?.cell || zone?.pointAnalysis?.cell || null;
    const municipality = pointAnalysis?.municipality || zone?.pointAnalysis?.municipality || null;
    const meta = FOCUS_META[tab];
    const ref = focus ? LAYER_REFERENCE[focus] : null;
    // only show evidence that belongs to the tab being viewed (a stale response for another
    // layer is hidden while the right one loads)
    const data = explanationData && !explanationData._unavailable && (explanationData.focus || null) === focus
        ? explanationData : null;
    const cls = data ? CLASS_STYLE[data.classification] || null : null;

    const placeName = pointAnalysis?.place?.label || zone?.name;
    const title = cityLabel && !municipality?.name && !zone?.municipality_name ? `${placeName}, ${cityLabel}` : placeName;
    const subtitle = [
        municipality?.name ? `${municipality.name} municipality` : null,
        cell?.cell_code ? `cell ${cell.cell_code}` : null,
        `${cell?.resolution_m || 300} m analytical cell`,
    ].filter(Boolean).join(" · ");

    let n = 0;
    const num = () => String(++n).padStart(2, "0");
    const waiting = (
        <Card><Muted>{explanationLoading || (explanationData && !data) ? "Gathering the evidence for this layer…" : "No analysis available for this location (outside the study region or no data)."}</Muted></Card>
    );

    const layerBody = focus && (
        <>
            <AtAGlance focus={focus} meta={meta} refInfo={ref} cell={cell} pixel={pixel} metrics={metrics}
                zone={zone} explanationData={data} provenance={provenance} />
            <Section n={num()} title="What the data shows" hint="Measured values, model results and the rules applied to them">
                {data ? <SummaryBlock data={data} focus={focus} aiPending={aiPending} /> : waiting}
            </Section>
            {!data || (data.supporting_measures || []).length ? (
                <Section n={num()} title="The measurements behind it"
                    hint="Each sub-layer, what it says about this area compared with the city, and the source that explains it">
                    {data ? <SupportingMeasures data={data} /> : waiting}
                </Section>
            ) : null}
            {focus === "composite" && (
                <Section n={num()} title="What makes up the score here" hint="For the 300 m area · each part scaled 0 (least concern) to 1 (most)">
                    <Card>
                        <CompositeBreakdown breakdown={cell?.metrics?.composite_breakdown || pixel?.composite?.breakdown}
                            value={cell?.metrics?.composite ?? pixel?.composite?.value}
                            onArea={!!cell?.metrics?.composite_breakdown} />
                        <PointNote pixel={pixel} />
                    </Card>
                </Section>
            )}
            {(!data || hasRelationships(data)) && <Section n={num()} title="How the layers affect each other here"
                hint={focus === "composite" ? "What usually goes together across the city, and whether this area fits" : `What usually goes with ${meta.short} across the city, and whether this area fits`}>
                {data ? <Relationships data={data} /> : waiting}
            </Section>}
            {focus !== "aqi" && focus !== "water_health" && hasTimeOrder(data) && (
                <Section n={num()} title="Which came first: heat or greenery?"
                    hint="From the seasonal history — does heat come before plants lose greenery, and does greening come with cooling?">
                    {data ? <TimeOrder data={data} /> : waiting}
                </Section>
            )}
            <Section n={num()} title="Over time" hint="Same season, year by year — the monsoon months are left out (cloud cover)">
                <Card>{data ? <SeasonChart history={data.evidence?.history} focus={focus} /> : <Muted>…</Muted>}</Card>
            </Section>
            <Section n={num()} title="Why it might be like this" hint="Associated factors, each with its supporting source">
                {data ? <Factors data={data} /> : waiting}
            </Section>
            <Section n={num()} title="What would help" hint="Scientifically backed measures; ★ = suited to this location's evidence">
                {data ? <Mitigation data={data} /> : waiting}
            </Section>
            <Section n={num()} title="Model check" hint={focus === "composite" ? "Every model for this cell" : `Only the models for ${meta.short}`}>
                {data ? <ModelCheck data={data} focus={focus} /> : waiting}
            </Section>
            <Section n={num()} title="Ask GeoSense" hint="Answers use this location's data and the cited knowledge base">
                {data ? <Ask data={data} focus={focus} /> : waiting}
            </Section>
            <Section n={num()} title="Sources & limits" hint="Documents and notes retrieved by RAG for this layer at this location">
                {data ? <Sources data={data} focus={focus} /> : waiting}
            </Section>
        </>
    );

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-label={`Deep analysis: ${title}`}
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 60,
                backgroundColor: "rgba(3, 5, 8, 0.85)",
                backdropFilter: "blur(24px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                opacity: isOpen ? 1 : 0,
                pointerEvents: isOpen ? "auto" : "none",
                transition: "opacity 0.3s ease",
            }}
            onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}
        >
            <div
                className="glass"
                style={{
                    width: "94%",
                    maxWidth: 1080,
                    height: "92%",
                    maxHeight: 960,
                    borderRadius: 16,
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                    border: `1px solid ${meta.color}33`,
                    boxShadow: "0 0 60px rgba(0, 229, 255, 0.05)",
                    transform: isOpen ? "scale(1)" : "scale(0.98)",
                    transition: "transform 0.4s cubic-bezier(0.22, 1, 0.36, 1)",
                }}
            >
                {/* ── Header ─────────────────────────────────────────── */}
                <header
                    style={{
                        padding: "18px 28px 12px",
                        display: "flex",
                        gap: 16,
                        alignItems: "flex-start",
                        flexShrink: 0,
                        background: `linear-gradient(to bottom, ${meta.color}0d, transparent)`,
                    }}
                >
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                            <Tag color="#00e5ff">Deep analysis</Tag>
                            {cls && <Tag color={cls.color}>{cls.label}</Tag>}
                        </div>
                        <h2 style={{ margin: 0, fontFamily: "'Syne', sans-serif", fontSize: "1.8rem", fontWeight: 700, color: "white", lineHeight: 1.15 }}>
                            {title}
                        </h2>
                        <div
                            style={{ fontSize: "0.74rem", color: "var(--text-dim)", letterSpacing: "0.04em", marginTop: 4 }}
                            title={pixel?.latitude != null ? `${pixel.latitude.toFixed(5)}°N, ${pixel.longitude.toFixed(5)}°E` : ""}
                        >
                            {subtitle}
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        aria-label="Close deep analysis"
                        style={{
                            background: "none",
                            border: "1px solid rgba(0,229,255,0.3)",
                            borderRadius: 6,
                            color: "var(--text-dim)",
                            width: 36,
                            height: 36,
                            cursor: "pointer",
                            fontSize: "16px",
                            flexShrink: 0,
                        }}
                    >
                        ✕
                    </button>
                </header>

                {/* ── Tabs: one layer at a time, or everything in Composite ── */}
                <nav
                    role="tablist"
                    aria-label="Layer"
                    style={{ display: "flex", padding: "0 20px", borderBottom: "1px solid rgba(0,229,255,0.1)", flexShrink: 0, overflowX: "auto" }}
                >
                    {TAB_ORDER.map((t) => {
                        const m = FOCUS_META[t];
                        const active = tab === t;
                        return (
                            <button
                                key={t}
                                role="tab"
                                aria-selected={active}
                                onClick={() => setTab(t)}
                                style={{
                                    padding: "14px 16px 12px",
                                    marginLeft: t === "models" ? "auto" : 0,
                                    background: "none",
                                    border: "none",
                                    borderBottom: `2px solid ${active ? m.color : "transparent"}`,
                                    color: active ? "white" : "var(--text-dim)",
                                    opacity: active ? 1 : 0.65,
                                    fontFamily: "'DM Mono', monospace",
                                    fontSize: "0.72rem",
                                    letterSpacing: "0.12em",
                                    textTransform: "uppercase",
                                    cursor: "pointer",
                                    whiteSpace: "nowrap",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                }}
                            >
                                <span style={{ color: m.color, fontSize: "0.8rem" }}>{m.icon}</span>
                                {m.tab}
                            </button>
                        );
                    })}
                </nav>

                {/* ── Body: one column ───────────────────────────────── */}
                <div ref={bodyRef} style={{ flex: 1, overflowY: "auto", padding: "22px 28px 36px" }}>
                    {/* everything inside is drawn 15% larger (easier to read); the column is narrowed to match */}
                    <div style={{ maxWidth: 860, margin: "0 auto", display: "grid", gap: 26, zoom: 1.15 }}>
                        {isModels ? <ModelsPanel summary={mlSummary} /> : layerBody}
                    </div>
                </div>
            </div>
        </div>
    );
}

function Tag({ color, children }) {
    return (
        <span style={{ fontSize: "0.58rem", letterSpacing: "0.16em", textTransform: "uppercase", padding: "4px 9px", borderRadius: 4, color, background: `${color}14`, border: `1px solid ${color}55` }}>
            {children}
        </span>
    );
}

// ── At a glance ──────────────────────────────────────────────────────────────
// One number for the layer in view: the 300 m cell average (what the models use), with the
// exact clicked point as one small line. The composite view shows every layer side by side.

function cellValues(cell, metrics) {
    const m = cell?.metrics || {};
    return {
        // vegetation of the area's land (water excluded), as the analysis uses
        ndvi: m.ndvi_land ?? m.ndvi ?? metrics.ndvi ?? null,
        lst: m.lst ?? metrics.lst ?? null,
        aqi: m.aqi ?? metrics.aqi ?? null,
        water_health: m.water_health_score ?? metrics.water_health_score ?? null,
    };
}

function pointValues(pixel) {
    const ok = (o) => o && !o.nodata;
    return {
        ndvi: ok(pixel?.ndvi) ? pixel.ndvi.value : null,
        lst: ok(pixel?.lst) ? pixel.lst.value_c : null,
        aqi: ok(pixel?.aqi) ? pixel.aqi.value : null,
        water_health: ok(pixel?.water_health) ? pixel.water_health.value : null,
    };
}

const SHOW = {
    ndvi: { d: 2, unit: "" , pointRes: "10 m pixel" },
    lst: { d: 1, unit: "°C", pointRes: "30 m pixel" },
    aqi: { d: 0, unit: "", pointRes: "interpolated" },
    water_health: { d: 3, unit: "", pointRes: "10 m pixel" },
};

function bandFor(layer, v, whPct) {
    if (v == null) return layer === "water_health" ? "NO WATER HERE" : "NO DATA";
    if (layer === "aqi") return getAqiCpcbBand(v);
    if (layer === "ndvi") return getNdviBand(v);
    if (layer === "lst") return getLstBand(v);
    if (layer === "water_health") return waterBandFromPercentile(whPct) || "—";
    return "";
}

function AtAGlance({ focus, meta, refInfo, cell, pixel, metrics, zone, explanationData, provenance }) {
    const cv = cellValues(cell, metrics);
    const pv = pointValues(pixel);
    const whPct = waterPercentileFromExplanation(explanationData);

    if (focus === "composite") {
        // the 300 m area's composite (from the current layers); the exact point only if the area has none
        const areaScore = cell?.metrics?.composite != null ? cell.metrics.composite * 100 : null;
        const score = areaScore ?? zone?.composite?.score ?? null;
        const color = compositeColor(score);
        return (
            <Card style={{ display: "grid", gridTemplateColumns: "minmax(170px, 220px) 1fr", gap: 20, alignItems: "center" }}>
                <div>
                    <div style={{ fontSize: "0.56rem", letterSpacing: "0.14em", color: "var(--text-dim)" }}>
                        COMPOSITE STRESS · {areaScore != null ? "300 M AREA" : "AT THIS POINT"}
                    </div>
                    <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "3rem", fontWeight: 700, color, lineHeight: 1.05 }}>
                        {score == null ? "N/A" : Math.round(score)}
                        <span style={{ fontSize: "0.9rem", color: "var(--text-dim)" }}> / 100</span>
                    </div>
                    <div style={{ fontSize: "0.78rem", fontWeight: 600, letterSpacing: "0.14em", color }}>{compositeBand(score)}</div>
                </div>
                <div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
                        {/* only the layers this area has (no "no water here" / "no data" tiles) */}
                        {["lst", "ndvi", "water_health", "aqi"].filter((l) => cv[l] != null).map((l) => (
                            <MiniTile key={l} layer={l} cell={cv[l]} point={pv[l]}
                                band={l === "water_health" && cv[l] != null ? `${bandFor(l, cv[l], whPct)} · water in area` : bandFor(l, cv[l], whPct)} />
                        ))}
                    </div>
                    <div style={{ marginTop: 8, display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                        <ProvenanceBadge prov={provFor(provenance, "composite")} />
                        <AboutMetric refInfo={refInfo} />
                    </div>
                </div>
            </Card>
        );
    }

    const v = cv[focus];
    const p = pv[focus];
    const s = SHOW[focus];
    const stress = focus === "water_health" && whPct != null ? 100 - whPct : normalizeMetric(focus, metrics);
    const color = v == null ? "rgba(255,255,255,0.5)" : getSeverityColor(stress);
    return (
        <Card style={{ display: "grid", gridTemplateColumns: "minmax(170px, 230px) 1fr", gap: 22, alignItems: "center" }}>
            <div>
                <div style={{ fontSize: "0.56rem", letterSpacing: "0.14em", color: "var(--text-dim)" }}>{meta.short.toUpperCase()} · 300 M CELL AVERAGE</div>
                <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "3rem", fontWeight: 700, color, lineHeight: 1.05, textShadow: `0 0 26px ${color}40` }}>
                    {v == null ? "N/A" : fmt(v, s.d)}
                    {s.unit && v != null && <span style={{ fontSize: "1rem" }}> {s.unit}</span>}
                </div>
                <div style={{ fontSize: "0.78rem", fontWeight: 600, letterSpacing: "0.14em", color }}>{bandFor(focus, v, whPct)}</div>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
                <div style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.85)", lineHeight: 1.55 }}>
                    {refInfo.definition}
                </div>
                {p != null && (
                    <div style={{ fontSize: "0.66rem", color: "var(--text-dim)" }}>
                        At the exact point you clicked: <b style={{ color: "white", fontFamily: "'DM Mono', monospace" }}>{fmt(p, s.d)}{s.unit ? ` ${s.unit}` : ""}</b> ({s.pointRes})
                    </div>
                )}
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                    <ProvenanceBadge prov={provFor(provenance, focus)} />
                    <AboutMetric refInfo={refInfo} />
                </div>
            </div>
        </Card>
    );
}

const MINI = {
    lst: { name: "Surface heat · LST", color: "#ff6a3d" },
    ndvi: { name: "Vegetation · NDVI", color: "#1dd1a1" },
    water_health: { name: "Water Health", color: "#2ec5ff" },
    aqi: { name: "Air (AQI)", color: "#ffb347" },
};

function MiniTile({ layer, cell, point, band }) {
    const s = SHOW[layer];
    const m = MINI[layer];
    return (
        <div style={{ padding: "8px 10px", background: "rgba(255,255,255,0.03)", borderRadius: 8, borderTop: `2px solid ${m.color}` }}
            title={point != null ? `Exact point: ${fmt(point, s.d)}${s.unit ? " " + s.unit : ""} (${s.pointRes})` : ""}>
            <div style={{ fontSize: "0.54rem", letterSpacing: "0.12em", color: "var(--text-dim)", textTransform: "uppercase" }}>{m.name}</div>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: "1.05rem", color: cell == null ? "rgba(255,255,255,0.4)" : m.color, marginTop: 2 }}>
                {cell == null ? "—" : `${fmt(cell, s.d)}${s.unit ? " " + s.unit : ""}`}
            </div>
            <div style={{ fontSize: "0.52rem", color: "rgba(200,214,229,0.6)", marginTop: 2 }}>{band}</div>
        </div>
    );
}

function AboutMetric({ refInfo }) {
    const [open, setOpen] = useState(false);
    return (
        <div style={{ position: "relative" }}>
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                style={{ background: "none", border: "none", padding: 0, color: "rgba(0,229,255,0.85)", fontSize: "0.6rem", letterSpacing: "0.1em", cursor: "pointer" }}
            >
                {open ? "▾" : "▸"} HOW IT IS MEASURED & BANDS
            </button>
            {open && (
                <div style={{ marginTop: 8, display: "grid", gap: 8, maxWidth: 640 }}>
                    <div style={{ fontSize: "0.68rem", color: "var(--text-dim)", lineHeight: 1.5 }}>
                        <b style={{ color: "white" }}>{refInfo.metric}</b> · {refInfo.method}
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {refInfo.bands.map((b) => (
                            <span key={b.label} style={{ padding: "3px 8px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, fontSize: "0.58rem", color: "var(--text-dim)" }}>
                                <span style={{ color: "white", marginRight: 4 }}>{b.range}</span>{b.label}
                            </span>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function resolveActiveLayerId(activeLayers) {
    if (!activeLayers) return "composite";
    if (activeLayers.all) return "composite";
    const selected = LAYER_PRIORITY.filter((layerId) => activeLayers[layerId]);
    if (selected.length === 1) return selected[0];
    return "composite";
}

// ── Composite v2 breakdown ─────────────────────────────────────────────────

const COMPONENT_META = {
    heat: { label: "Heat · LST", color: "#ff8a3d" },
    surface: { label: "Surface · NDVI on land, Water Health on water", color: "#5fd38d",
        note: "lack of vegetation on land pixels · poor Water Health on water pixels (a pixel is one or the other)" },
    air: { label: "Air · AQI", color: "#c58cff" },
};

// The exact clicked point, as a side note under the area's analysis.
function PointNote({ pixel }) {
    if (!pixel) return null;
    const ok = (o) => o && !o.nodata;
    const parts = [
        ok(pixel.ndvi) && `NDVI ${Number(pixel.ndvi.value).toFixed(2)}`,
        ok(pixel.lst) ? `LST ${Number(pixel.lst.value_c).toFixed(1)} °C` : "LST missing (cloud gap)",
        ok(pixel.water_health) && `Water Health ${Number(pixel.water_health.value).toFixed(3)}`,
        ok(pixel.aqi) && `AQI ${pixel.aqi.value}`,
        ok(pixel.composite) && pixel.composite.value != null && `composite ${Math.round(pixel.composite.value * 100)}/100`,
    ].filter(Boolean);
    return (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.06)", fontSize: "0.6rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
            At the exact point you clicked: {parts.join(" · ")}.
        </div>
    );
}

function CompositeBreakdown({ breakdown, value, onArea = false }) {
    if ((!breakdown || !Object.keys(breakdown.components || {}).length) && value != null) {
        return (
            <div style={{ fontSize: "0.65rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
                Composite {onArea ? "for this 300 m area" : "here"}: <b style={{ color: "white" }}>{Number(value).toFixed(2)}</b>. The
                per-part breakdown appears once the composite has been regenerated with the v2 method
                (scripts/generate_composite_surface.py).
            </div>
        );
    }
    if (!breakdown) {
        return (
            <div style={{ fontSize: "0.65rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
                No composite value here: fewer than 2 of the 3 parts (heat, surface, air) are available. Missing
                inputs are never treated as zero or healthy.
            </div>
        );
    }
    const order = ["heat", "surface", "air"];
    return (
        <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "var(--text-dim)", marginBottom: 10 }}>
                <span>Score <b style={{ color: "white", fontFamily: "'DM Mono', monospace" }}>{breakdown.score.toFixed(2)}</b> / 1</span>
                <span>{breakdown.coverage} parts {onArea ? "· 300 m area" : "· exact point"}</span>
            </div>
            <div style={{ display: "grid", gap: 10 }}>
                {order.filter((k) => breakdown.components?.[k]).map((k) => {
                    const c = breakdown.components?.[k];
                    const meta = COMPONENT_META[k];
                    return (
                        <div key={k} title={meta.note || ""}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.62rem", marginBottom: 4 }}>
                                <span style={{ color: c ? "var(--text-dim)" : "rgba(200,214,229,0.35)" }}>{meta.label}</span>
                                <span style={{ fontFamily: "'DM Mono', monospace", color: c ? meta.color : "rgba(200,214,229,0.35)" }}>
                                    {c ? `${c.value.toFixed(2)} × w${c.weight.toFixed(2)} → ${c.share_pct.toFixed(0)}%` : "not available"}
                                </span>
                            </div>
                            <div style={{ height: 4, background: "rgba(0,0,0,0.5)", borderRadius: 2, overflow: "hidden" }}>
                                {c && <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, c.share_pct))}%`, background: meta.color }} />}
                            </div>
                        </div>
                    );
                })}
            </div>
            <div style={{ fontSize: "0.55rem", color: "var(--text-faint, rgba(200,214,229,0.45))", marginTop: 10, lineHeight: 1.5 }}>
                Uses all four layers: heat from LST, surface from NDVI (land) or Water Health (water), air from AQI.
                Each part is scaled 0 (least concern) to 1 (most); weights 0.40 / 0.35 / 0.25 are renormalised over the
                parts present{breakdown.missing?.length ? ` (missing here: ${breakdown.missing.join(", ")})` : ""}; at least 2 of 3
                are required. GeoSense-derived index, not an official one.
            </div>
        </div>
    );
}

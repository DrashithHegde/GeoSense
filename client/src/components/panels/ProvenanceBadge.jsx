// Small data-provenance line: source · resolution · images/stations · date, with a freshness dot.
// Data comes from GET /api/provenance (read from the surface manifest).

const LAYER_TO_PROV = { all: "composite", composite: "composite", water: "water_health" };

export function provFor(provenance, layerId) {
  if (!provenance || !layerId) return null;
  return provenance[LAYER_TO_PROV[layerId] || layerId] || null;
}

function fullText(p) {
  if (!p) return "";
  if (!p.available) return `${p.label}: not available — ${p.reason || "not generated"}`;
  if (p.layer === "aqi") {
    return [
      `${p.label}: ${p.sensor}`,
      `${p.stations} stations; newest reading ${p.age_hours != null ? `${p.age_hours} h ago` : "time unknown"}`,
      p.freshness_rule,
      p.resolution,
      p.validation_mae != null ? `Leave-one-station-out error: ±${p.validation_mae} AQI` : null,
    ].filter(Boolean).join("\n");
  }
  return [
    `${p.label}: ${p.sensor}${p.dataset ? ` (${p.dataset})` : ""}`,
    p.period_start ? `Composite period: ${p.period_start} → ${p.period_end}` : p.period_end ? `Date: ${p.period_end}` : null,
    p.resolution_m ? `Resolution: ${p.resolution_m} m${p.resolution_note ? ` (${p.resolution_note})` : ""}` : null,
    p.images ? `Images combined: ${p.images}` : null,
    p.age_days != null ? `Age: ${p.age_days} days` : null,
    p.derived_from ? `Derived from ${p.derived_from.toUpperCase()}` : null,
    p.layer === "composite" ? "GeoSense-derived index, not an official government index" : null,
    p.method ? `Method: ${p.method}` : null,
  ].filter(Boolean).join("\n");
}

export default function ProvenanceBadge({ prov, compact = false, style = {} }) {
  if (!prov) return null;
  const color = !prov.available
    ? "rgba(200,214,229,0.35)"
    : prov.freshness === "current"
      ? "#3ddc84"
      : prov.freshness === "stale"
        ? "#ff6b6b"
        : "#f5b942";
  const age = prov.available
    ? prov.layer === "aqi"
      ? prov.age_hours != null ? ` · ${prov.age_hours < 1 ? "<1" : Math.round(prov.age_hours)} h old` : ""
      : prov.age_days != null ? ` · ${prov.age_days} d old` : ""
    : "";
  const text = prov.available ? `${prov.short}${compact ? "" : age}` : "not available";
  return (
    <div
      title={fullText(prov)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        minWidth: 0,
        maxWidth: "100%",
        fontFamily: "'DM Mono', monospace",
        fontSize: compact ? "0.46rem" : "0.55rem",
        letterSpacing: "0.03em",
        color: "var(--text-faint, rgba(200,214,229,0.45))",
        cursor: "help",
        ...style,
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{text}</span>
    </div>
  );
}

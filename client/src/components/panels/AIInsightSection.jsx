import { useEffect, useState } from "react";
import { askAssistant } from "../../hooks/useGeoSenseData";

// ─────────────────────────────────────────────────────────────────────────────
// AIInsightSection
// Compact summary for the side panel (headline + first measure), plus the shared building
// blocks (Ask box, mitigation list, model cards…) used by DeepAnalysisSections.jsx.
// Every number shown comes from the backend evidence object (/api/analysis/point/explain).
// ─────────────────────────────────────────────────────────────────────────────

export const LEVEL_COLOR = {
  warning: "#ff5a5a",
  notice: "#ffb347",
  info: "#5ad1ff",
};

export const CLASS_STYLE = {
  anomaly: { label: "FLAGGED BY MODELS", color: "#ff3bd4" },
  elevated: { label: "ELEVATED SIGNAL", color: "#ff8c00" },
  notice: { label: "NOTABLE CONDITIONS", color: "#ffd23c" },
  inlier: { label: "NO UNUSUAL SIGNAL", color: "#29d967" },
};

export const LAYER_META = {
  ndvi: { name: "NDVI · vegetation", accent: "#29d967", bad: "low" },
  lst: { name: "LST · surface heat", accent: "#ff6a3d", bad: "high" },
  water_health: { name: "Water Health", accent: "#2ec5ff", bad: "low" },
  aqi: { name: "AQI", accent: "#ffb347", bad: "high" },
};
const LAYER_ORDER = ["ndvi", "lst", "water_health", "aqi"];
export const FOCUS_NAME = {
  composite: "ALL LAYERS",
  ndvi: "NDVI",
  lst: "LST",
  water_health: "WATER HEALTH",
  aqi: "AQI",
};
export const SUGGESTED = {
  composite: ["What stands out here overall?", "What would improve this area?", "How reliable is this analysis?"],
  ndvi: ["Why is vegetation low here?", "Is this greener than nearby areas?", "What would increase green cover?"],
  lst: ["Why is it hot here?", "Is this hotter than its land cover explains?", "What would cool this block?"],
  water_health: ["Why is water health low here?", "Is this water worse than nearby water?", "How can this be confirmed on the ground?"],
  aqi: ["Why is AQI like this here?", "Which pollutant dominates nearby?", "Who is most at risk at this AQI?"],
};

export function Chip({ children, color = "255,59,212" }) {
  return (
    <span
      style={{
        fontSize: "0.6rem",
        padding: "2px 6px",
        borderRadius: 4,
        background: `rgba(${color},0.08)`,
        border: `1px solid rgba(${color},0.25)`,
        color: "rgba(255,255,255,0.8)",
      }}
    >
      {children}
    </span>
  );
}

export function LayerIFCard({ layer, r, focused, models = {} }) {
  // When another model already flagged this layer, say so, so "not flagged" here doesn't look contradictory.
  const otherFlag =
    !r.is_anomaly &&
    ((layer === "water_health" && ["low_water_condition", "high_water_condition"].includes(models.water_health?.flag))
      ? "the Water Health z-score model flags this cell (see its card)"
      : layer === "lst" && ["unexplained_heat", "unexplained_cooling"].includes(models.xgboost_lst?.flag)
        ? "XGBoost flags this cell's temperature as unexplained (see its card)"
        : layer === "aqi" && models.station_isolation_forest?.is_anomaly
          ? "the nearest station has an unusual pollutant mix (see the station card)"
          : null);
  const meta = LAYER_META[layer];
  const word =
    r.direction === "high" ? "unusually HIGH" : r.direction === "low" ? "unusually LOW" : "unusual PATTERN";
  const bad = r.is_anomaly && r.direction === meta.bad;
  return (
    <ModelCard
      title={`Isolation Forest · ${meta.name}${focused ? " · this tab" : ""}`}
      accent={meta.accent}
    >
      <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}>
        {r.is_anomaly ? (
          <b style={{ color: bad ? "#ff5a5a" : "#ffd23c" }}>Flagged: {word}</b>
        ) : (
          <span>Not flagged</span>
        )}{" "}
        · score higher than {r.score_percentile}% of cells
      </div>
      {otherFlag && (
        <div style={{ marginTop: 4, fontSize: "0.62rem", color: "#ffd23c", lineHeight: 1.5 }}>
          Not an outlier for this Isolation Forest, but {otherFlag}. The models answer different questions.
        </div>
      )}
      <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
        {(r.dominant_deviations || []).map((d) => (
          <Chip key={d.feature}>
            {d.label} {d.z > 0 ? "+" : ""}
            {d.z}σ
          </Chip>
        ))}
      </div>
    </ModelCard>
  );
}

export function ContributionBars({ contributions }) {
  const entries = Object.entries(contributions || {}).sort(
    (a, b) => Math.abs(b[1]) - Math.abs(a[1]),
  );
  const max = Math.max(0.5, ...entries.map(([, v]) => Math.abs(v)));
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {entries.map(([label, v]) => (
        <div
          key={label}
          style={{
            display: "grid",
            gridTemplateColumns: "130px 1fr 52px",
            alignItems: "center",
            gap: 8,
            fontSize: "0.62rem",
          }}
        >
          <span style={{ color: "rgba(200,214,229,0.75)" }}>{label}</span>
          <div
            style={{
              position: "relative",
              height: 6,
              background: "rgba(255,255,255,0.05)",
              borderRadius: 3,
            }}
          >
            <div
              style={{
                position: "absolute",
                left: "50%",
                top: 0,
                bottom: 0,
                width: `${(Math.abs(v) / max) * 50}%`,
                transform: v < 0 ? "translateX(-100%)" : "none",
                background: v > 0 ? "#ff6a3d" : "#2ec5ff",
                borderRadius: 3,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: "50%",
                top: -2,
                bottom: -2,
                width: 1,
                background: "rgba(255,255,255,0.25)",
              }}
            />
          </div>
          <span
            style={{
              fontFamily: "'DM Mono', monospace",
              textAlign: "right",
              color: v > 0 ? "#ff8a66" : "#6ad6ff",
            }}
          >
            {v > 0 ? "+" : ""}
            {v.toFixed(1)}°C
          </span>
        </div>
      ))}
    </div>
  );
}

export function ModelCard({ title, children, accent }) {
  return (
    <div
      style={{
        padding: "12px 14px",
        background: "rgba(255,255,255,0.025)",
        border: `1px solid ${accent}33`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: "0.55rem",
          letterSpacing: "0.18em",
          color: accent,
          marginBottom: 8,
          textTransform: "uppercase",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

export function AskBox({ lon, lat, focus, suggestions = null }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  // a new spot or tab starts a fresh conversation
  useEffect(() => {
    setAnswer(null);
    setQ("");
  }, [lon, lat, focus]);
  const ask = async (text, intent = null) => {
    if (!text || text.trim().length < 3) return;
    setQ(text);
    setBusy(true);
    try {
      setAnswer(await askAssistant(text.trim(), lon, lat, focus, intent));
    } catch (err) {
      setAnswer({ answer: `Assistant unavailable: ${err.message}`, citations: [] });
    } finally {
      setBusy(false);
    }
  };
  const submit = async (e) => {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    try {
      setAnswer(await askAssistant(q.trim(), lon, lat, focus));
    } catch (err) {
      setAnswer({ answer: `Assistant unavailable: ${err.message}`, citations: [] });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        {(suggestions?.length ? suggestions : (SUGGESTED[focus] || SUGGESTED.composite).map((q) => ({ id: null, q }))).map(({ id, q: t }) => (
          <button
            key={t}
            type="button"
            disabled={busy}
            onClick={() => ask(t, id)}
            style={{
              background: "rgba(0,229,255,0.06)",
              border: "1px solid rgba(0,229,255,0.25)",
              borderRadius: 12,
              color: "rgba(255,255,255,0.8)",
              padding: "3px 9px",
              fontSize: "0.6rem",
              cursor: busy ? "wait" : "pointer",
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <form onSubmit={submit} style={{ display: "flex", gap: 8 }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask about this location, e.g. why is it hot? what would help?"
          style={{
            flex: 1,
            background: "rgba(0,0,0,0.35)",
            border: "1px solid rgba(0,229,255,0.25)",
            borderRadius: 6,
            padding: "8px 10px",
            color: "white",
            fontSize: "0.75rem",
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={busy}
          style={{
            background: "rgba(0,229,255,0.12)",
            border: "1px solid rgba(0,229,255,0.45)",
            borderRadius: 6,
            color: "#00e5ff",
            padding: "0 14px",
            fontSize: "0.65rem",
            letterSpacing: "0.12em",
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "…" : "ASK"}
        </button>
      </form>
      {answer && (
        <div
          style={{
            marginTop: 10,
            fontSize: "0.78rem",
            lineHeight: 1.6,
            color: "rgba(255,255,255,0.88)",
          }}
        >
          {answer.answer}
          {answer.citations?.length > 0 && (
            <div style={{ marginTop: 6, fontSize: "0.6rem", color: "var(--text-dim)" }}>
              Sources: {answer.citations.map((c) => c.title).join(" · ")}
            </div>
          )}
          {answer.mode && (
            <div style={{ marginTop: 4, fontSize: "0.55rem", color: "var(--text-faint)" }}>
              {answer.mode === "llm_validated"
                ? `AI answer (${answer.llm?.provider}) · checked against this location's data`
                : answer.mode === "evidence"
                  ? "Answer computed from this location's data"
                  : "Outside what GeoSense can answer from its data"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Details({ label, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginTop: 8 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: "rgba(0,229,255,0.85)",
          fontSize: "0.6rem",
          letterSpacing: "0.08em",
          cursor: "pointer",
        }}
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}

export function Bullets({ items }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {items.map((it, i) => (
        <div key={i} style={{ display: "flex", gap: 8, fontSize: "0.74rem", lineHeight: 1.5 }}>
          <span style={{ color: it.color || "#5ad1ff", flexShrink: 0 }}>●</span>
          <span style={{ color: "rgba(255,255,255,0.86)" }}>{it.text}</span>
        </div>
      ))}
    </div>
  );
}

export function MitigationList({ mit, fallback }) {
  if (!mit) {
    return fallback?.length ? <Bullets items={fallback.map((t) => ({ text: t, color: "#29d967" }))} /> : null;
  }
  if (!mit.items?.length) {
    return <div style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>{mit.note}</div>;
  }
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {mit.note && <div style={{ fontSize: "0.62rem", color: "var(--text-dim)" }}>{mit.note}</div>}
      {mit.items.map((it) => (
        <div key={it.layer + it.key} style={{ display: "flex", gap: 8, fontSize: "0.74rem", lineHeight: 1.5 }}>
          <span style={{ color: it.fits_this_cell ? "#29d967" : "rgba(41,217,103,0.45)", flexShrink: 0 }}>
            {it.fits_this_cell ? "★" : "•"}
          </span>
          <span style={{ color: "#d4f7dd" }}>
            {it.text}
            {it.fits_this_cell && it.why && (
              <span style={{ color: "rgba(255,255,255,0.45)", fontSize: "0.62rem" }}> — fits here: {it.why}</span>
            )}
            {it.evidence?.cite && (
              <span style={{ display: "block", fontSize: "0.58rem", color: "rgba(159,232,176,0.55)" }}>
                Evidence:{" "}
                {it.evidence.url ? (
                  <a href={it.evidence.url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{it.evidence.cite}</a>
                ) : it.evidence.cite}
              </span>
            )}
          </span>
        </div>
      ))}
      <div style={{ fontSize: "0.55rem", color: "var(--text-faint)" }}>
        ★ = matches this cell's evidence · each measure lists its scientific or official source
      </div>
    </div>
  );
}

export function ModelLines({ models, focus }) {
  const L = models.layer_isolation_forest || {};
  const word = (r) =>
    !r ? null : r.is_anomaly
      ? `flagged — unusually ${r.direction === "pattern" ? "patterned" : r.direction?.toUpperCase()}`
      : "not flagged";
  const lines = [];
  const x = models.xgboost_lst;
  if ((focus === "lst" || focus === "composite" || !focus) && x) {
    const flag = x.flag === "unexplained_heat" ? "unexplained HEAT" : x.flag === "unexplained_cooling" ? "unexplained COOLING" : "consistent with land cover";
    lines.push({ k: "xgb", c: x.flag === "unexplained_heat" ? "#ff5a5a" : "#ff8a66",
      t: `XGBoost: observed ${x.observed_lst_c} °C vs expected ${x.expected_lst_c} °C → ${flag}` });
  }
  if (focus && focus !== "composite" && L[focus]) {
    lines.push({ k: "lif", c: L[focus].is_anomaly ? "#ffd23c" : "#8fa3b8",
      t: `Isolation Forest (${LAYER_META[focus].name}): ${word(L[focus])}` });
  }
  if (focus === "water_health" && models.water_health) {
    const w = models.water_health;
    lines.push({ k: "wh", c: w.flag === "low_water_condition" ? "#ff5a5a" : "#8fa3b8",
      t: `Water Health z-score: ${w.robust_z} (percentile ${w.percentile} among water cells)${w.flag === "low_water_condition" ? " → low condition" : ""}` });
  }
  if (focus === "aqi" && models.station_isolation_forest) {
    const st = models.station_isolation_forest;
    lines.push({ k: "st", c: st.is_anomaly ? "#ffb347" : "#8fa3b8",
      t: `Nearest station ${st.station_name}: ${st.is_anomaly ? "unusual pollutant mix" : "typical pollutant mix"}` });
  }
  if (focus === "composite" || !focus) {
    const i = models.isolation_forest;
    if (i) lines.push({ k: "if", c: i.is_anomaly ? "#ff3bd4" : "#8fa3b8", t: `Combined Isolation Forest: ${i.is_anomaly ? "flagged" : "not flagged"}` });
    const n = Object.values(L).filter((r) => r?.is_anomaly).length;
    lines.push({ k: "n", c: "#8fa3b8", t: `Layer Isolation Forests flagging this cell: ${n} of ${Object.keys(L).length}` });
  }
  if (!lines.length) {
    return <div style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>No model output for this layer here.</div>;
  }
  return (
    <div style={{ display: "grid", gap: 4 }}>
      {lines.map((l) => (
        <div key={l.k} style={{ fontSize: "0.7rem", color: "rgba(255,255,255,0.85)", display: "flex", gap: 8 }}>
          <span style={{ color: l.c }}>■</span>
          <span>{l.t}</span>
        </div>
      ))}
    </div>
  );
}

export default function AIInsightSection({ explanationData, loading, compact = true }) {
  if (loading || !explanationData) {
    return (
      <div style={{ color: "var(--text-dim)", fontSize: "0.8rem" }}>
        Building evidence and retrieving knowledge…
      </div>
    );
  }
  if (explanationData._unavailable) {
    return (
      <div style={{ color: "var(--text-dim)", fontSize: "0.8rem", fontStyle: "italic" }}>
        {explanationData.reason || "No analysis available for this location (outside the study region or no data)."}
      </div>
    );
  }

  const ex = explanationData.explanation || {};
  const cls = CLASS_STYLE[explanationData.classification] || CLASS_STYLE.inlier;
  return (
      <div>
        <div
          style={{
            fontSize: "0.55rem",
            letterSpacing: "0.18em",
            color: cls.color,
            marginBottom: 6,
          }}
        >
          ● {cls.label}
        </div>
        <div style={{ fontSize: "0.74rem", lineHeight: 1.55, color: "rgba(255,255,255,0.9)" }}>
          {ex.summary}
        </div>
        {(explanationData.mitigation?.items?.[0]?.text || ex.what_could_help?.[0]) && (
          <div style={{ marginTop: 6, fontSize: "0.66rem", color: "#9fe8b0", lineHeight: 1.5 }}>
            ↳ {explanationData.mitigation?.items?.[0]?.text || ex.what_could_help[0]}
          </div>
        )}
      </div>
  );
  // The full Deep Analysis layout lives in DeepAnalysisSections.jsx (one component per section).
}


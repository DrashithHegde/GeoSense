import { useState } from "react";
import { askAssistant } from "../../hooks/useGeoSenseData";

// ─────────────────────────────────────────────────────────────────────────────
// AIInsightSection
// Renders the point explanation from /api/analysis/point/explain:
//   evidence signals → ML model cards → recommendations → cited knowledge,
// plus a grounded "Ask GeoSense" box (/api/assistant/ask).
// Every number shown here comes from the backend evidence object.
// ─────────────────────────────────────────────────────────────────────────────

const LEVEL_COLOR = {
  warning: "#ff5a5a",
  notice: "#ffb347",
  info: "#5ad1ff",
};

const CLASS_STYLE = {
  anomaly: { label: "FLAGGED BY MODELS", color: "#ff3bd4" },
  elevated: { label: "ELEVATED SIGNAL", color: "#ff8c00" },
  notice: { label: "NOTABLE CONDITIONS", color: "#ffd23c" },
  inlier: { label: "NO UNUSUAL SIGNAL", color: "#29d967" },
};

const LAYER_META = {
  ndvi: { name: "NDVI · vegetation", accent: "#29d967", bad: "low" },
  lst: { name: "LST · surface heat", accent: "#ff6a3d", bad: "high" },
  water_health: { name: "Water Health", accent: "#2ec5ff", bad: "low" },
  aqi: { name: "CPCB AQI", accent: "#ffb347", bad: "high" },
};
const LAYER_ORDER = ["ndvi", "lst", "water_health", "aqi"];
const FOCUS_NAME = {
  composite: "ALL LAYERS",
  ndvi: "NDVI",
  lst: "LST",
  water_health: "WATER HEALTH",
  aqi: "AQI",
};
const SUGGESTED = {
  composite: [
    "What stands out here overall?",
    "What would improve this area?",
    "How reliable is this analysis?",
  ],
  ndvi: [
    "Why is vegetation low here?",
    "Is this greener than nearby areas?",
    "What would increase green cover?",
  ],
  lst: [
    "Why is it hot here?",
    "Is this hotter than its land cover explains?",
    "What would cool this block?",
  ],
  water_health: [
    "Why is water health low here?",
    "Is this water worse than nearby water?",
    "How can this be confirmed on the ground?",
  ],
  aqi: [
    "Why is AQI like this here?",
    "Which pollutant dominates nearby?",
    "Who is most at risk at this AQI?",
  ],
};

function orderedLayers(focus) {
  return focus && LAYER_ORDER.includes(focus)
    ? [focus, ...LAYER_ORDER.filter((l) => l !== focus)]
    : LAYER_ORDER;
}

function Chip({ children, color = "255,59,212" }) {
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

function LayerIFCard({ layer, r, focused, models = {} }) {
  // When another model already flagged this layer, say so, so "not flagged" here doesn't look contradictory.
  const otherFlag =
    !r.is_anomaly &&
    (layer === "water_health" &&
    ["low_water_condition", "high_water_condition"].includes(
      models.water_health?.flag,
    )
      ? "the Water Health z-score model flags this cell (see its card)"
      : layer === "lst" &&
          ["unexplained_heat", "unexplained_cooling"].includes(
            models.xgboost_lst?.flag,
          )
        ? "XGBoost flags this cell's temperature as unexplained (see its card)"
        : layer === "aqi" && models.station_isolation_forest?.is_anomaly
          ? "the nearest station has an unusual pollutant mix (see the station card)"
          : null);
  const meta = LAYER_META[layer];
  const word =
    r.direction === "high"
      ? "unusually HIGH"
      : r.direction === "low"
        ? "unusually LOW"
        : "unusual PATTERN";
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
        <div
          style={{
            marginTop: 4,
            fontSize: "0.62rem",
            color: "#ffd23c",
            lineHeight: 1.5,
          }}
        >
          Not an outlier for this Isolation Forest, but {otherFlag}. The models
          answer different questions.
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

function SectionTitle({ children }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        margin: "18px 0 10px",
      }}
    >
      <div
        style={{ width: 3, height: 12, background: "var(--cyan, #00e5ff)" }}
      />
      <div
        style={{
          fontSize: "0.62rem",
          letterSpacing: "0.2em",
          color: "rgba(255,255,255,0.85)",
          textTransform: "uppercase",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function ContributionBars({ contributions }) {
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

function ModelCard({ title, children, accent }) {
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

function AskBox({ lon, lat, focus }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const ask = async (text) => {
    if (!text || text.trim().length < 3) return;
    setQ(text);
    setBusy(true);
    try {
      setAnswer(await askAssistant(text.trim(), lon, lat, focus));
    } catch (err) {
      setAnswer({
        answer: `Assistant unavailable: ${err.message}`,
        citations: [],
      });
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
      setAnswer({
        answer: `Assistant unavailable: ${err.message}`,
        citations: [],
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <div
        style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}
      >
        {(SUGGESTED[focus] || SUGGESTED.composite).map((t) => (
          <button
            key={t}
            type="button"
            disabled={busy}
            onClick={() => ask(t)}
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
            <div
              style={{
                marginTop: 6,
                fontSize: "0.6rem",
                color: "var(--text-dim)",
              }}
            >
              Sources: {answer.citations.map((c) => c.title).join(" · ")}
            </div>
          )}
          {answer.mode && (
            <div
              style={{
                marginTop: 4,
                fontSize: "0.55rem",
                color: "var(--text-faint)",
              }}
            >
              {answer.mode === "llm_validated"
                ? `AI answer (${answer.llm?.provider}) · checked against evidence`
                : "Evidence-only answer from the knowledge base" +
                  (answer.warnings?.length ? ` — ${answer.warnings[0]}` : "")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Details({ label, children, defaultOpen = false }) {
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

function Bullets({ items }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {items.map((it, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            gap: 8,
            fontSize: "0.74rem",
            lineHeight: 1.5,
          }}
        >
          <span style={{ color: it.color || "#5ad1ff", flexShrink: 0 }}>●</span>
          <span style={{ color: "rgba(255,255,255,0.86)" }}>{it.text}</span>
        </div>
      ))}
    </div>
  );
}

function MitigationList({ mit, fallback }) {
  if (!mit) {
    return fallback?.length ? (
      <Bullets items={fallback.map((t) => ({ text: t, color: "#29d967" }))} />
    ) : null;
  }
  if (!mit.items?.length) {
    return (
      <div style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>
        {mit.note}
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {mit.note && (
        <div style={{ fontSize: "0.62rem", color: "var(--text-dim)" }}>
          {mit.note}
        </div>
      )}
      {mit.items.map((it) => (
        <div
          key={it.layer + it.key}
          style={{
            display: "flex",
            gap: 8,
            fontSize: "0.74rem",
            lineHeight: 1.5,
          }}
        >
          <span
            style={{
              color: it.fits_this_cell ? "#29d967" : "rgba(41,217,103,0.45)",
              flexShrink: 0,
            }}
          >
            {it.fits_this_cell ? "★" : "•"}
          </span>
          <span style={{ color: "#d4f7dd" }}>
            {it.text}
            {it.fits_this_cell && it.why && (
              <span
                style={{ color: "rgba(255,255,255,0.45)", fontSize: "0.62rem" }}
              >
                {" "}
                — fits here: {it.why}
              </span>
            )}
          </span>
        </div>
      ))}
      <div style={{ fontSize: "0.55rem", color: "var(--text-faint)" }}>
        ★ = matches this cell's evidence · measures from the cited mitigation
        notes
      </div>
    </div>
  );
}

function ModelLines({ models, focus }) {
  const L = models.layer_isolation_forest || {};
  const word = (r) =>
    !r
      ? null
      : r.is_anomaly
        ? `flagged — unusually ${r.direction === "pattern" ? "patterned" : r.direction?.toUpperCase()}`
        : "not flagged";
  const lines = [];
  const x = models.xgboost_lst;
  if ((focus === "lst" || focus === "composite" || !focus) && x) {
    const flag =
      x.flag === "unexplained_heat"
        ? "unexplained HEAT"
        : x.flag === "unexplained_cooling"
          ? "unexplained COOLING"
          : "consistent with land cover";
    lines.push({
      k: "xgb",
      c: x.flag === "unexplained_heat" ? "#ff5a5a" : "#ff8a66",
      t: `XGBoost: observed ${x.observed_lst_c} °C vs expected ${x.expected_lst_c} °C → ${flag}`,
    });
  }
  if (focus && focus !== "composite" && L[focus]) {
    lines.push({
      k: "lif",
      c: L[focus].is_anomaly ? "#ffd23c" : "#8fa3b8",
      t: `Isolation Forest (${LAYER_META[focus].name}): ${word(L[focus])}`,
    });
  }
  if (focus === "water_health" && models.water_health) {
    const w = models.water_health;
    lines.push({
      k: "wh",
      c: w.flag === "low_water_condition" ? "#ff5a5a" : "#8fa3b8",
      t: `Water Health z-score: ${w.robust_z} (percentile ${w.percentile} among water cells)${w.flag === "low_water_condition" ? " → low condition" : ""}`,
    });
  }
  if (focus === "aqi" && models.station_isolation_forest) {
    const st = models.station_isolation_forest;
    lines.push({
      k: "st",
      c: st.is_anomaly ? "#ffb347" : "#8fa3b8",
      t: `Nearest station ${st.station_name}: ${st.is_anomaly ? "unusual pollutant mix" : "typical pollutant mix"}`,
    });
  }
  if (focus === "composite" || !focus) {
    const i = models.isolation_forest;
    if (i)
      lines.push({
        k: "if",
        c: i.is_anomaly ? "#ff3bd4" : "#8fa3b8",
        t: `Combined Isolation Forest: ${i.is_anomaly ? "flagged" : "not flagged"}`,
      });
    const n = Object.values(L).filter((r) => r?.is_anomaly).length;
    lines.push({
      k: "n",
      c: "#8fa3b8",
      t: `Layer Isolation Forests flagging this cell: ${n} of ${Object.keys(L).length}`,
    });
  }
  if (!lines.length) {
    return (
      <div style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>
        No model output for this layer here.
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 4 }}>
      {lines.map((l) => (
        <div
          key={l.k}
          style={{
            fontSize: "0.7rem",
            color: "rgba(255,255,255,0.85)",
            display: "flex",
            gap: 8,
          }}
        >
          <span style={{ color: l.c }}>■</span>
          <span>{l.t}</span>
        </div>
      ))}
    </div>
  );
}

export default function AIInsightSection({
  explanationData,
  loading,
  compact = false,
  focus = null,
}) {
  if (loading || !explanationData) {
    return (
      <div style={{ color: "var(--text-dim)", fontSize: "0.8rem" }}>
        Building evidence and retrieving knowledge…
      </div>
    );
  }
  if (explanationData._unavailable) {
    return (
      <div
        style={{
          color: "var(--text-dim)",
          fontSize: "0.8rem",
          fontStyle: "italic",
        }}
      >
        No analysis available for this location (outside study region or no
        data).
      </div>
    );
  }

  const ex = explanationData.explanation || {};
  const cls = CLASS_STYLE[explanationData.classification] || CLASS_STYLE.inlier;
  const models = explanationData.evidence?.models || {};
  const loc = explanationData.location || {};
  const gen = explanationData.generation || {};

  if (compact) {
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
        <div
          style={{
            fontSize: "0.74rem",
            lineHeight: 1.55,
            color: "rgba(255,255,255,0.9)",
          }}
        >
          {ex.summary}
        </div>
        {(explanationData.mitigation?.items?.[0]?.text ||
          ex.what_could_help?.[0]) && (
          <div
            style={{
              marginTop: 6,
              fontSize: "0.66rem",
              color: "#9fe8b0",
              lineHeight: 1.5,
            }}
          >
            ↳{" "}
            {explanationData.mitigation?.items?.[0]?.text ||
              ex.what_could_help[0]}
          </div>
        )}
      </div>
    );
  }

  const mit = explanationData.mitigation;
  const signals = explanationData.signals || [];
  const keyFindings = signals.slice(0, 3);
  const factors = (ex.why_it_might_be || []).slice(0, 2);
  const cites = explanationData.citations || [];
  const limits = (ex.caveats || []).filter(
    (c) => !/statistical associations/i.test(c),
  );

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            padding: "3px 8px",
            border: `1px solid ${cls.color}`,
            color: cls.color,
            borderRadius: 4,
            fontSize: "0.55rem",
            letterSpacing: "0.18em",
          }}
        >
          {cls.label}
        </span>
        {focus && FOCUS_NAME[focus] && (
          <span
            style={{
              padding: "3px 8px",
              border: "1px solid rgba(0,229,255,0.4)",
              color: "#00e5ff",
              borderRadius: 4,
              fontSize: "0.55rem",
              letterSpacing: "0.18em",
            }}
          >
            FOCUS · {FOCUS_NAME[focus]}
          </span>
        )}
        <span
          style={{
            fontSize: "0.55rem",
            color: "var(--text-faint)",
            letterSpacing: "0.1em",
          }}
        >
          EVIDENCE WRITE-UP · FROM DATA, MODELS & CITED KNOWLEDGE
        </span>
      </div>
      <div
        style={{
          marginTop: 10,
          fontSize: "0.95rem",
          color: "white",
          lineHeight: 1.45,
        }}
      >
        {ex.headline}
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: "0.82rem",
          color: "rgba(255,255,255,0.8)",
          lineHeight: 1.6,
        }}
      >
        {ex.summary}
      </div>

      {explanationData.ai_summary && (
        <div
          style={{
            marginTop: 12,
            padding: "10px 12px",
            borderRadius: 6,
            background: "rgba(0,229,255,0.05)",
            border: "1px solid rgba(0,229,255,0.22)",
          }}
        >
          <div
            style={{
              fontSize: "0.52rem",
              letterSpacing: "0.18em",
              color: "#00e5ff",
              marginBottom: 4,
            }}
          >
            IN PLAIN WORDS · AI ({(gen.llm?.provider || "").toUpperCase()}) ·
            CHECKED AGAINST THE EVIDENCE
          </div>
          <div
            style={{
              fontSize: "0.8rem",
              lineHeight: 1.6,
              color: "rgba(255,255,255,0.9)",
            }}
          >
            {explanationData.ai_summary}
          </div>
        </div>
      )}

      <SectionTitle>Key findings</SectionTitle>
      <Bullets
        items={keyFindings.map((x) => ({
          text: x.text,
          color: LEVEL_COLOR[x.level],
        }))}
      />
      {signals.length > 3 && (
        <Details label={`All findings (${signals.length})`}>
          <Bullets
            items={signals
              .slice(3)
              .map((x) => ({ text: x.text, color: LEVEL_COLOR[x.level] }))}
          />
        </Details>
      )}

      {factors.length > 0 && (
        <>
          <SectionTitle>Possible factors</SectionTitle>
          <Bullets
            items={factors.map((t) => ({ text: t, color: "#b9a6ff" }))}
          />
        </>
      )}

      <SectionTitle>
        Mitigation strategies{mit?.title ? ` · ${mit.title}` : ""}
      </SectionTitle>
      <MitigationList mit={mit} fallback={ex.what_could_help} />

      <SectionTitle>Model check</SectionTitle>
      <ModelLines models={models} focus={focus} />
      <Details label="All model details">
        <div style={{ display: "grid", gap: 10 }}>
          {focus && models.layer_isolation_forest?.[focus] && (
            <LayerIFCard
              layer={focus}
              r={models.layer_isolation_forest[focus]}
              focused
              models={models}
            />
          )}
          {models.xgboost_lst && (
            <ModelCard
              title="XGBoost · expected vs observed surface heat"
              accent="#ff6a3d"
            >
              <div
                style={{
                  fontSize: "0.72rem",
                  color: "rgba(255,255,255,0.85)",
                  marginBottom: 8,
                }}
              >
                Observed {models.xgboost_lst.observed_lst_c} °C · expected{" "}
                {models.xgboost_lst.expected_lst_c} °C · residual{" "}
                <b
                  style={{
                    color:
                      models.xgboost_lst.residual_c > 0 ? "#ff8a66" : "#6ad6ff",
                  }}
                >
                  {models.xgboost_lst.residual_c > 0 ? "+" : ""}
                  {models.xgboost_lst.residual_c} °C
                </b>{" "}
                <span style={{ color: "var(--text-faint)" }}>
                  (spatial-CV R² {models.xgboost_lst.cv_r2}, RMSE{" "}
                  {models.xgboost_lst.cv_rmse_c} °C)
                </span>
              </div>
              <ContributionBars
                contributions={
                  explanationData.point_analysis?.cell?.models
                    ?.xgboost_lst_residual_v1?.evidence?.contributions_c
                }
              />
            </ModelCard>
          )}
          {models.isolation_forest && (
            <ModelCard
              title="Isolation Forest · multivariate outlier"
              accent="#ff3bd4"
            >
              <div
                style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}
              >
                {models.isolation_forest.is_anomaly ? "Flagged" : "Not flagged"}{" "}
                · anomaly score higher than{" "}
                {models.isolation_forest.score_percentile}% of cells
              </div>
              <div
                style={{
                  marginTop: 6,
                  display: "flex",
                  gap: 6,
                  flexWrap: "wrap",
                }}
              >
                {(models.isolation_forest.dominant_deviations || []).map(
                  (d) => (
                    <span
                      key={d.feature}
                      style={{
                        fontSize: "0.6rem",
                        padding: "2px 6px",
                        borderRadius: 4,
                        background: "rgba(255,59,212,0.08)",
                        border: "1px solid rgba(255,59,212,0.25)",
                        color: "rgba(255,255,255,0.8)",
                      }}
                    >
                      {d.label} {d.z > 0 ? "+" : ""}
                      {d.z}σ
                    </span>
                  ),
                )}
              </div>
            </ModelCard>
          )}
          {models.water_health && (
            <ModelCard title="Water Health · robust z-score" accent="#ffd23c">
              <div
                style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}
              >
                Cell water index {models.water_health.wh_mean} · z ={" "}
                {models.water_health.robust_z} · percentile{" "}
                {models.water_health.percentile} among water cells
              </div>
            </ModelCard>
          )}
          {models.station_isolation_forest && (
            <ModelCard
              title="Isolation Forest · nearest AQI station"
              accent="#ffb347"
            >
              <div
                style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}
              >
                {models.station_isolation_forest.station_name}:{" "}
                {models.station_isolation_forest.is_anomaly ? (
                  <b style={{ color: "#ffb347" }}>unusual pollutant mix</b>
                ) : (
                  "typical pollutant mix"
                )}{" "}
                vs other stations
              </div>
              <div
                style={{
                  marginTop: 6,
                  display: "flex",
                  gap: 6,
                  flexWrap: "wrap",
                }}
              >
                {(
                  models.station_isolation_forest.dominant_deviations || []
                ).map((d) => (
                  <Chip key={d.pollutant} color="255,179,71">
                    {d.pollutant} {d.sub_index} ({d.z > 0 ? "+" : ""}
                    {d.z}σ)
                  </Chip>
                ))}
              </div>
            </ModelCard>
          )}
          {models.layer_isolation_forest && (
            <div style={{ display: "grid", gap: 10 }}>
              {orderedLayers(focus)
                .filter((l) => l !== focus && models.layer_isolation_forest[l])
                .map((l) => (
                  <LayerIFCard
                    key={l}
                    layer={l}
                    r={models.layer_isolation_forest[l]}
                    models={models}
                  />
                ))}
            </div>
          )}
          {!models.xgboost_lst &&
            !models.isolation_forest &&
            !models.water_health &&
            !models.layer_isolation_forest && (
              <div style={{ fontSize: "0.72rem", color: "var(--text-dim)" }}>
                No model output for this cell (insufficient cloud-free data).
              </div>
            )}
        </div>
      </Details>

      <div
        style={{
          marginTop: 12,
          fontSize: "0.6rem",
          color: "var(--text-faint)",
          lineHeight: 1.5,
        }}
      >
        Limits: statistical associations from one satellite snapshot, not proof
        of cause
        {limits.length
          ? ` · ${limits.map((c) => c.replace(/[.\s]+$/, "")).join(" · ")}`
          : ""}
        .
      </div>

      <SectionTitle>Ask GeoSense</SectionTitle>
      <AskBox
        lon={loc.longitude}
        lat={loc.latitude}
        focus={focus || "composite"}
      />

      {cites.length > 0 && (
        <Details
          label={`Sources · knowledge retrieved by RAG (${cites.length})`}
        >
          {explanationData.rag?.mode && (
            <div
              style={{
                fontSize: "0.55rem",
                color: "var(--text-faint)",
                marginBottom: 6,
              }}
            >
              Retrieval: {explanationData.rag.mode}
              {explanationData.rag.recall_at_5 != null &&
                ` · right note in top 5 for ${Math.round(explanationData.rag.recall_at_5 * 100)}% of ${explanationData.rag.eval_questions} test questions`}
            </div>
          )}
          <div style={{ display: "grid", gap: 4 }}>
            {cites.map((c) => (
              <div
                key={c.knowledge_id}
                style={{
                  fontSize: "0.6rem",
                  color: "var(--text-dim)",
                  lineHeight: 1.5,
                }}
              >
                {c.url ? (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "rgba(0,229,255,0.85)" }}
                  >
                    {c.title}
                  </a>
                ) : (
                  <span style={{ color: "rgba(255,255,255,0.75)" }}>
                    {c.title}
                  </span>
                )}{" "}
                — {c.source}
              </div>
            ))}
          </div>
        </Details>
      )}
      {gen.warnings?.length > 0 && (
        <div
          style={{
            marginTop: 10,
            fontSize: "0.55rem",
            color: "var(--text-faint)",
          }}
        >
          {gen.warnings.join(" · ")}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CityModelCards — city-wide model cards for the current snapshot (real ML run)
// ─────────────────────────────────────────────────────────────────────────────
export function CityModelCards({ explanationData, focus = null }) {
  const mc = explanationData?.model_cards;
  if (!mc || !Object.keys(mc).length) {
    return (
      <div
        style={{
          color: "var(--text-dim)",
          fontSize: "0.8rem",
          fontStyle: "italic",
        }}
      >
        Model cards appear after the ML pipeline has run.
      </div>
    );
  }
  const x = mc.xgboost_lst || {};
  const i = mc.isolation_forest || {};
  const w = mc.water_health || {};
  const imp = Object.entries(x.feature_importance_gain || {}).sort(
    (a, b) => b[1] - a[1],
  );
  const row = (k, v) => (
    <div
      key={k}
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: "0.68rem",
        padding: "3px 0",
      }}
    >
      <span style={{ color: "var(--text-dim)" }}>{k}</span>
      <span style={{ color: "white", fontFamily: "'DM Mono', monospace" }}>
        {v}
      </span>
    </div>
  );
  return (
    <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
      <div
        style={{
          fontSize: "0.7rem",
          color: "var(--text-dim)",
          letterSpacing: "0.2em",
        }}
      >
        CITY MODEL CARDS · SNAPSHOT {String(mc.snapshot_at || "").slice(0, 10)}
      </div>
      {x.metrics && (
        <div
          style={{
            fontSize: "0.66rem",
            color: "rgba(255,255,255,0.8)",
            lineHeight: 1.6,
          }}
        >
          XGBoost heat model: spatial-CV R² {x.metrics.r2_spatial_cv.toFixed(2)}
          , error ±{x.metrics.rmse_c.toFixed(1)} °C ·{" "}
          {x.flags?.unexplained_heat ?? 0} unexplained-heat cells
          {w.flags && (
            <>
              {" "}
              · Water Health: {w.flags.low_water_condition} low-condition water
              cells
            </>
          )}
        </div>
      )}
      {mc.layer_isolation_forest && (
        <ModelCard title="Isolation Forest · per layer" accent="#00e5ff">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 52px 52px 40px 40px",
              gap: 4,
              fontSize: "0.55rem",
              color: "var(--text-dim)",
              letterSpacing: "0.08em",
              paddingBottom: 4,
            }}
          >
            <span>LAYER</span>
            <span style={{ textAlign: "right" }}>CELLS</span>
            <span style={{ textAlign: "right" }}>FLAGGED</span>
            <span style={{ textAlign: "right" }}>HIGH</span>
            <span style={{ textAlign: "right" }}>LOW</span>
          </div>
          {orderedLayers(focus).map((l) => {
            const r = mc.layer_isolation_forest[l];
            if (!r) return null;
            const ok = r.status === "ok";
            return (
              <div
                key={l}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 52px 52px 40px 40px",
                  gap: 4,
                  fontSize: "0.66rem",
                  padding: "3px 0",
                  color: l === focus ? "#00e5ff" : "white",
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                <span style={{ fontFamily: "inherit" }}>
                  {LAYER_META[l].name}
                </span>
                {ok ? (
                  <>
                    <span style={{ textAlign: "right" }}>{r.eligible}</span>
                    <span style={{ textAlign: "right" }}>{r.anomalies}</span>
                    <span style={{ textAlign: "right" }}>
                      {r.unusually_high}
                    </span>
                    <span style={{ textAlign: "right" }}>
                      {r.unusually_low}
                    </span>
                  </>
                ) : (
                  <span
                    style={{
                      gridColumn: "span 4",
                      textAlign: "right",
                      color: "var(--text-dim)",
                    }}
                  >
                    not enough data
                  </span>
                )}
              </div>
            );
          })}
          <div
            style={{
              marginTop: 6,
              fontSize: "0.55rem",
              color: "var(--text-faint)",
              lineHeight: 1.5,
            }}
          >
            NDVI, LST and Water Health: cell value, within-cell variability and
            contrast with the surrounding 1 km. AQI: interpolated value only
            (station model below covers pollutant mix).
          </div>
        </ModelCard>
      )}
      <Details label="All city model cards">
        <div style={{ display: "grid", gap: 16 }}>
          <ModelCard title="XGBoost surface-heat model" accent="#ff6a3d">
            {x.metrics &&
              row("Spatial-CV R²", x.metrics.r2_spatial_cv.toFixed(2))}
            {x.metrics &&
              row(
                "RMSE / MAE",
                `${x.metrics.rmse_c.toFixed(1)} / ${x.metrics.mae_c.toFixed(1)} °C`,
              )}
            {x.metrics && row("Cells modelled", x.metrics.n_cells)}
            {x.flags && row("Unexplained heat cells", x.flags.unexplained_heat)}
            <div
              style={{
                marginTop: 8,
                fontSize: "0.55rem",
                letterSpacing: "0.15em",
                color: "var(--text-dim)",
              }}
            >
              FEATURE IMPORTANCE (GAIN)
            </div>
            {imp.map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 90px 34px",
                  gap: 6,
                  alignItems: "center",
                  marginTop: 4,
                  fontSize: "0.6rem",
                }}
              >
                <span style={{ color: "rgba(200,214,229,0.75)" }}>{k}</span>
                <div
                  style={{
                    height: 4,
                    background: "rgba(255,255,255,0.06)",
                    borderRadius: 2,
                  }}
                >
                  <div
                    style={{
                      width: `${(v * 100) / (imp[0]?.[1] || 1)}%`,
                      height: "100%",
                      background: "#ff6a3d",
                      borderRadius: 2,
                    }}
                  />
                </div>
                <span style={{ textAlign: "right", color: "white" }}>
                  {Math.round(v * 100)}%
                </span>
              </div>
            ))}
          </ModelCard>
          <ModelCard title="Isolation Forest" accent="#ff3bd4">
            {row("Cells eligible", i.eligible)}
            {row("Flagged outliers", i.anomalies)}
            {i.excluded_water_cells != null &&
              row(
                "Water cells (scored by Water Health)",
                i.excluded_water_cells,
              )}
            {row(
              "Excluded (cloud / coverage)",
              i.excluded_water_cells != null
                ? i.excluded - i.excluded_water_cells
                : i.excluded,
            )}
            {row("Contamination", i.contamination)}
          </ModelCard>
          <ModelCard title="Water Health baseline" accent="#ffd23c">
            {row("Water cells", w.eligible)}
            {w.median != null && row("Median index", w.median.toFixed(3))}
            {w.flags && row("Low-condition cells", w.flags.low_water_condition)}
          </ModelCard>
          {mc.station_isolation_forest && (
            <ModelCard title="Isolation Forest · AQI stations" accent="#ffb347">
              {mc.station_isolation_forest.status === "ok" ? (
                <>
                  {row(
                    "Stations compared",
                    mc.station_isolation_forest.eligible,
                  )}
                  {row(
                    "Unusual pollutant mix",
                    mc.station_isolation_forest.anomalies,
                  )}
                  {row(
                    "Pollutants used",
                    (mc.station_isolation_forest.pollutants || []).join(", "),
                  )}
                  {(mc.station_isolation_forest.stations || [])
                    .filter((x) => x.is_anomaly)
                    .slice(0, 5)
                    .map((x) => (
                      <div
                        key={x.station_name}
                        style={{
                          fontSize: "0.6rem",
                          color: "#ffd9a8",
                          marginTop: 3,
                        }}
                      >
                        • {x.station_name}:{" "}
                        {(x.dominant_deviations || [])
                          .slice(0, 2)
                          .map(
                            (d) =>
                              `${d.pollutant} ${d.z > 0 ? "+" : ""}${d.z}σ`,
                          )
                          .join(", ")}
                      </div>
                    ))}
                </>
              ) : (
                <div style={{ fontSize: "0.66rem", color: "var(--text-dim)" }}>
                  Not enough stations with pollutant data in this run.
                </div>
              )}
            </ModelCard>
          )}
        </div>
      </Details>
      <div
        style={{
          fontSize: "0.6rem",
          color: "var(--text-faint)",
          lineHeight: 1.5,
        }}
      >
        Statistical signals from one satellite snapshot — associations, not
        proof of cause.
      </div>
    </div>
  );
}

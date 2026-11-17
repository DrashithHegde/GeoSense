import { useState } from "react";
import {
  AskBox,
  Bullets,
  Chip,
  CLASS_STYLE,
  ContributionBars,
  Details,
  LayerIFCard,
  LEVEL_COLOR,
  MitigationList,
  ModelCard,
  ModelLines,
} from "./AIInsightSection";

// ─────────────────────────────────────────────────────────────────────────────
// DeepAnalysisSections — one component per Deep Analysis section.
// All content comes from GET /api/analysis/point/explain (evidence, rules, models, RAG).
// Single-layer view: only that layer's findings and models. Composite view: everything.
// ─────────────────────────────────────────────────────────────────────────────

export function Section({ n, title, hint, children, accent = "var(--cyan, #00e5ff)" }) {
  return (
    <section style={{ display: "grid", gap: 10 }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.62rem", color: accent }}>{n}</span>
        <div>
          <h3 style={{ margin: 0, fontSize: "0.76rem", letterSpacing: "0.16em", color: "white", textTransform: "uppercase", fontWeight: 600 }}>
            {title}
          </h3>
          {hint && <div style={{ fontSize: "0.6rem", color: "rgba(200,214,229,0.55)", marginTop: 2 }}>{hint}</div>}
        </div>
      </header>
      <div>{children}</div>
    </section>
  );
}

export function Card({ children, style = {} }) {
  return (
    <div style={{ padding: "14px 16px", background: "rgba(0,0,0,0.26)", border: "1px solid rgba(0,229,255,0.12)", borderRadius: 10, ...style }}>
      {children}
    </div>
  );
}

// 01 · What the data shows: headline, evidence summary, AI plain words, key findings
export function SummaryBlock({ data, focus, aiPending }) {
  const ex = data.explanation || {};
  const gen = data.generation || {};
  const cls = CLASS_STYLE[data.classification] || CLASS_STYLE.inlier;
  const signals = data.signals || [];
  const keyFindings = (data.key_findings?.length ? data.key_findings : signals.slice(0, 3)).filter((k) => k.text !== ex.summary);
  // composite = all details: every finding; single layer = only that layer's findings
  const others = focus === "composite"
    ? signals.filter((x) => x.text !== ex.summary && !keyFindings.some((k) => k.id === x.id && k.text === x.text))
    : [];
  return (
    <Card>
      <span style={{ display: "inline-block", padding: "3px 8px", border: `1px solid ${cls.color}`, color: cls.color, borderRadius: 4, fontSize: "0.55rem", letterSpacing: "0.16em" }}>
        {cls.label}
      </span>
      <div style={{ marginTop: 10, fontSize: "0.98rem", color: "white", lineHeight: 1.45 }}>{ex.summary}</div>

      {data.ai_summary ? (
        <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 6, background: "rgba(0,229,255,0.05)", borderLeft: "3px solid rgba(0,229,255,0.6)" }}>
          <div style={{ fontSize: "0.52rem", letterSpacing: "0.16em", color: "#00e5ff", marginBottom: 4 }}>
            IN PLAIN WORDS · AI ({(gen.llm?.provider || "").toUpperCase()}) · CHECKED AGAINST THE DATA
          </div>
          <div style={{ fontSize: "0.82rem", lineHeight: 1.6, color: "rgba(255,255,255,0.9)" }}>{data.ai_summary}</div>
        </div>
      ) : aiPending ? (
        <div style={{ marginTop: 12, fontSize: "0.66rem", color: "rgba(0,229,255,0.75)" }} role="status">
          <span className="pulse-dot" style={{ marginRight: 6 }}>●</span>Writing a plain-words summary… (the evidence below is already final)
        </div>
      ) : null}

      {keyFindings.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: "0.55rem", letterSpacing: "0.16em", color: "rgba(200,214,229,0.6)", marginBottom: 6 }}>KEY FINDINGS</div>
          <Bullets items={keyFindings.map((x) => ({ text: x.text, color: LEVEL_COLOR[x.level] }))} />
        </div>
      )}
      {others.length > 0 && (
        <Details label={`All findings for this location (${others.length} more)`}>
          <Bullets items={others.map((x) => ({ text: x.text, color: LEVEL_COLOR[x.level] }))} />
        </Details>
      )}
    </Card>
  );
}

// 03 · Why it might be like this
export function Factors({ data }) {
  const factors = (data.explanation?.why_it_might_be || []).slice(0, 3);
  if (!factors.length) {
    return <Muted>No clear associated factor stands out for this layer here.</Muted>;
  }
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {factors.map((t, i) => {
        const ev = data.factor_evidence?.[i];
        return (
          <Card key={i} style={{ padding: "10px 14px" }}>
            <div style={{ fontSize: "0.76rem", lineHeight: 1.55, color: "rgba(255,255,255,0.88)" }}>{t}</div>
            {ev && (
              <div style={{ marginTop: 4, fontSize: "0.6rem", color: "rgba(185,166,255,0.85)" }} title={ev.excerpt || ev.source}>
                Supported by: {ev.url ? <a href={ev.url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{ev.title}</a> : ev.title}
              </div>
            )}
          </Card>
        );
      })}
      <Muted>These are associations seen in the data, not proven causes.</Muted>
    </div>
  );
}

// 04 · What would help
export function Mitigation({ data }) {
  const mit = data.mitigation;
  return (
    <Card>
      {mit?.title && <div style={{ fontSize: "0.8rem", color: "#9fe8b0", marginBottom: 8 }}>{mit.title}</div>}
      <MitigationList mit={mit} fallback={data.explanation?.what_could_help} />
    </Card>
  );
}

// 05 · Model check — only the models relevant to the layer in view
export function ModelCheck({ data, focus }) {
  const models = data.evidence?.models || {};
  const L = models.layer_isolation_forest || {};
  const contributions = data.point_analysis?.cell?.models?.xgboost_lst_residual_v1?.evidence?.contributions_c;
  const all = focus === "composite";
  const cards = [];
  if ((all || focus === "lst") && models.xgboost_lst) {
    const x = models.xgboost_lst;
    cards.push(
      <ModelCard key="xgb" title="XGBoost · expected vs observed heat" accent="#ff6a3d">
        <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)", marginBottom: 8 }}>
          Observed {x.observed_lst_c} °C · expected {x.expected_lst_c} °C from land cover · difference{" "}
          <b style={{ color: x.residual_c > 0 ? "#ff8a66" : "#6ad6ff" }}>{x.residual_c > 0 ? "+" : ""}{x.residual_c} °C</b>
        </div>
        {contributions && (
          <>
            <div style={{ fontSize: "0.55rem", letterSpacing: "0.12em", color: "rgba(200,214,229,0.6)", marginBottom: 4 }}>WHAT PUSHES THE EXPECTED VALUE UP (+) OR DOWN (−)</div>
            <ContributionBars contributions={contributions} />
          </>
        )}
      </ModelCard>,
    );
  }
  if (all && models.isolation_forest) {
    const i = models.isolation_forest;
    cards.push(
      <ModelCard key="if" title="Isolation Forest · all land indicators together" accent="#ff3bd4">
        <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}>
          {i.is_anomaly ? "Flagged as unusual" : "Not unusual"} · more unusual than {i.score_percentile}% of cells
        </div>
        <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(i.dominant_deviations || []).map((d) => <Chip key={d.feature}>{d.label} {d.z > 0 ? "+" : ""}{d.z}σ</Chip>)}
        </div>
      </ModelCard>,
    );
  }
  if ((all || focus === "water_health") && models.water_health) {
    const w = models.water_health;
    cards.push(
      <ModelCard key="wh" title="Water Health · compared with all local water" accent="#2ec5ff">
        <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}>
          Index {w.wh_mean} · better than {w.percentile}% of water cells · z = {w.robust_z}
          {w.flag === "low_water_condition" && <b style={{ color: "#ff8a66" }}> · low condition</b>}
        </div>
      </ModelCard>,
    );
  }
  if ((all || focus === "aqi") && models.station_isolation_forest) {
    const st = models.station_isolation_forest;
    cards.push(
      <ModelCard key="st" title="Isolation Forest · nearest AQI station" accent="#ffb347">
        <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.85)" }}>
          {st.station_name}: {st.is_anomaly ? <b style={{ color: "#ffb347" }}>unusual pollutant mix</b> : "typical pollutant mix"} vs other stations
        </div>
        <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(st.dominant_deviations || []).map((d) => (
            <Chip key={d.pollutant} color="255,179,71">{d.pollutant} {d.sub_index} ({d.z > 0 ? "+" : ""}{d.z}σ)</Chip>
          ))}
        </div>
      </ModelCard>,
    );
  }
  const layers = all ? ["ndvi", "lst", "water_health", "aqi"] : [focus];
  layers.filter((l) => L[l]).forEach((l) => cards.push(<LayerIFCard key={`lif-${l}`} layer={l} r={L[l]} focused={!all} models={models} />));

  return (
    <Card>
      <ModelLines models={models} focus={focus} />
      {cards.length > 0 ? (
        <Details label="Model details">
          <div style={{ display: "grid", gap: 10 }}>{cards}</div>
        </Details>
      ) : (
        <Muted>No model output for this layer here (not enough cloud-free data).</Muted>
      )}
    </Card>
  );
}

// 07 · Sources (RAG) + limits
// words that tie a caveat to one layer; on a single-layer tab, other layers' caveats are hidden
const LAYER_WORDS = {
  aqi: /\b(AQI|CPCB|MPCB|OpenAQ|station|PM2\.5|PM10)\b/i,
  ndvi: /\b(NDVI|vegetation)\b/i,
  lst: /\b(LST|Landsat|surface temperature|heat)\b/i,
  water_health: /\b(Water Health|MNDWI|NDCI|turbidity)\b/i,
};

function caveatsFor(caveats, focus) {
  const base = (caveats || []).filter((c) => !/statistical associations/i.test(c));
  if (!focus || focus === "composite") return base;
  return base.filter((c) => LAYER_WORDS[focus]?.test(c) || !Object.entries(LAYER_WORDS).some(([k, re]) => k !== focus && re.test(c)));
}

export function Sources({ data, focus = null }) {
  const cites = data.citations || [];
  const ex = data.explanation || {};
  const limits = caveatsFor(ex.caveats, focus);
  return (
    <Card>
      {cites.length > 0 ? (
        <Details label={`Sources retrieved for this location (${cites.length})`}>
          {data.rag?.mode && (
            <div style={{ fontSize: "0.55rem", color: "var(--text-faint)", marginBottom: 6, lineHeight: 1.5 }}>
              How they were found: {data.rag.mode}
            </div>
          )}
          {["passage", "note"].map((kind) => {
            const group = cites.filter((c) => (c.kind || "note") === kind);
            if (!group.length) return null;
            return (
              <div key={kind} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: "0.52rem", letterSpacing: "0.16em", color: "var(--text-faint)", marginBottom: 4 }}>
                  {kind === "passage" ? "FROM SOURCE DOCUMENTS (WITH PAGE)" : "CURATED KNOWLEDGE NOTES"}
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {group.map((c) => (
                    <div key={c.knowledge_id} style={{ fontSize: "0.6rem", color: "var(--text-dim)", lineHeight: 1.5 }}>
                      {c.url ? (
                        <a href={c.url} target="_blank" rel="noreferrer" style={{ color: "rgba(0,229,255,0.85)" }}>{c.title}</a>
                      ) : (
                        <span style={{ color: "rgba(255,255,255,0.75)" }}>{c.title}</span>
                      )}
                      {c.source_type && (
                        <span style={{ marginLeft: 6, fontSize: "0.5rem", color: "rgba(159,232,176,0.7)", letterSpacing: "0.06em" }}>{c.source_type.toUpperCase()}</span>
                      )}
                      <div style={{ color: "var(--text-faint)" }}>{c.source}</div>
                      {c.excerpt && <div style={{ color: "rgba(255,255,255,0.55)", fontStyle: "italic" }}>“{c.excerpt}”</div>}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </Details>
      ) : (
        <Muted>No sources were retrieved for this location.</Muted>
      )}
      <div style={{ marginTop: 10, fontSize: "0.6rem", color: "rgba(200,214,229,0.6)", lineHeight: 1.55 }}>
        Limits: statistical associations from one satellite snapshot, not proof of cause
        {limits.length ? ` · ${limits.map((c) => c.replace(/[.\s]+$/, "")).join(" · ")}` : ""}.
      </div>
    </Card>
  );
}

export function Ask({ data, focus }) {
  const loc = data.location || {};
  return (
    <Card>
      <AskBox lon={loc.longitude} lat={loc.latitude} focus={focus || "composite"} suggestions={data.suggested_questions} />
    </Card>
  );
}

// How the layers relate, in plain words: the city-wide pattern, and whether this area fits it.
// The statistics (Spearman rho, number of areas, ranges) are one click away under "Show the numbers".
const PATTERN_COLOR = { "Strong pattern": "#5fd38d", "Clear pattern": "#7cc8ff", "Weak pattern": "#c8d6e5", "No real pattern": "#8a96a3" };

export function Relationships({ data }) {
  const all = data?.relationships || [];
  // On Composite (many pairs) keep what matters here: a pair this area can be judged on, or a
  // clear city-wide pattern; weak patterns with nothing to say about this area are left out.
  const items = all.filter((r) => r.strength === "moderate" || r.strength === "strong"
    || (r.strength === "weak" && r.here && r.here.verdict !== "about typical"));
  if (!items.length) return null;
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {items.map((r) => <RelationCard key={r.id} r={r} />)}
      <div style={{ fontSize: "0.68rem", color: "var(--text-dim)", lineHeight: 1.55 }}>
        A pattern is how two things usually change together across all 300 m areas of the city. It shows a link,
        not a cause: other things (building materials, wind, the day the satellite passed) also matter.
      </div>
    </div>
  );
}

function RelationCard({ r }) {
  const [open, setOpen] = useState(false);
  const pc = PATTERN_COLOR[r.pattern] || "#c8d6e5";
  const h = r.here;
  const off = h && h.verdict !== "about typical";
  const vc = !h ? null : !off ? "#5fd38d" : h.label.startsWith("Warmer") || h.label.startsWith("Higher") ? "#ffb84d" : "#5fc8ff";
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ fontSize: "0.95rem", color: "white", fontWeight: 600, lineHeight: 1.35 }}>{r.headline}</div>
        <span style={{ fontSize: "0.62rem", letterSpacing: "0.08em", color: pc, border: `1px solid ${pc}55`, borderRadius: 999, padding: "3px 10px", whiteSpace: "nowrap" }}>
          {r.pattern}
        </span>
      </div>

      {h && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, color: vc, background: `${vc}1f`, borderRadius: 6, padding: "3px 9px" }}>
              Here: {h.label}
            </span>
            <span style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.88)", lineHeight: 1.5 }}>{h.plain}</span>
          </div>
          <SimpleRange h={h} color={vc} />
        </div>
      )}
      {r.caution_plain && (
        <div style={{ marginTop: 10, fontSize: "0.74rem", color: "rgba(255,255,255,0.7)", lineHeight: 1.5 }}>{r.caution_plain}</div>
      )}

      <button type="button" onClick={() => setOpen((o) => !o)}
        style={{ marginTop: 10, background: "none", border: "none", padding: 0, color: "rgba(0,229,255,0.8)", fontSize: "0.64rem", letterSpacing: "0.08em", cursor: "pointer" }}>
        {open ? "▾ Hide the numbers" : "▸ Show the numbers"}
      </button>
      {open && (
        <div style={{ marginTop: 6, fontSize: "0.7rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
          <div>{r.title} · Spearman ρ {r.rho > 0 ? "+" : ""}{r.rho.toFixed(2)} ({r.strength}) across {r.n.toLocaleString()} areas.</div>
          <div>{r.city_text}</div>
          {h && <div>{h.text}</div>}
          {r.caution && <div>{r.caution}</div>}
        </div>
      )}
    </Card>
  );
}

// "usual range for similar places" as a band, this area as a dot, both labelled in plain words
function SimpleRange({ h, color }) {
  const [q25, q75] = h.range;
  const lo = Math.min(q25, h.y), hi = Math.max(q75, h.y);
  const pad = (hi - lo) * 0.3 || 1;
  const x = (v) => ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100;
  return (
    <div style={{ margin: "14px 6px 4px" }} aria-hidden="true">
      <div style={{ position: "relative", height: 18 }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 7, height: 4, background: "rgba(255,255,255,0.07)", borderRadius: 2 }} />
        <div style={{ position: "absolute", left: `${x(q25)}%`, width: `${Math.max(1, x(q75) - x(q25))}%`, top: 4, height: 10,
          background: "rgba(200,214,229,0.18)", border: "1px solid rgba(200,214,229,0.35)", borderRadius: 4 }} />
        <div style={{ position: "absolute", left: `calc(${x(h.y)}% - 8px)`, top: 1, width: 16, height: 16, borderRadius: "50%",
          background: color, boxShadow: `0 0 12px ${color}`, border: "2px solid #0b0f14" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginTop: 6, fontSize: "0.68rem", flexWrap: "wrap" }}>
        <span style={{ color: "rgba(200,214,229,0.75)" }}>▭ Usual for similar places: {h.range_text[0]} – {h.range_text[1]}</span>
        <span style={{ color }}>● This area: {h.y_text}</span>
      </div>
    </div>
  );
}

// Over time: which came first. City-wide patterns from the seasonal history, and what happened
// in this area over the latest pair of years.
export function TimeOrder({ data }) {
  // Only what actually happened here, backed by a pattern the whole city shows. Nothing is shown
  // when the area does not fit a real pattern (the section itself is then left out).
  const t = data?.time_order;
  const city = t?.city || {};
  const hits = (t?.here?.signals || []).map((sig) => ({
    sig, c: city[sig.id === "heat_stress_vegetation" ? "heat_then_greenery" : "greening_cooling"],
  })).filter((x) => x.c);
  if (!hits.length) return null;
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {hits.map(({ sig, c }) => <TimeCard key={sig.id} c={c} hit={sig} />)}
      <div style={{ fontSize: "0.68rem", color: "var(--text-dim)", lineHeight: 1.55 }}>
        From the same season in different years. This area is compared only with areas that started equally green,
        and changes are measured against the whole city's change. A link, not proof: rain, watering, tree cutting or
        construction can do the same.
      </div>
    </div>
  );
}

export function hasTimeOrder(data) {
  return !!(data?.time_order?.here?.signals || []).length;
}

function TimeCard({ c, hit }) {
  const [open, setOpen] = useState(false);
  const pc = PATTERN_COLOR[c.pattern] || "#c8d6e5";
  const vc = hit.id === "heat_stress_vegetation" ? "#ffb84d" : "#5fd38d";
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ fontSize: "0.95rem", color: "white", fontWeight: 600, lineHeight: 1.35 }}>{c.headline}</div>
        <span style={{ fontSize: "0.62rem", letterSpacing: "0.08em", color: pc, border: `1px solid ${pc}55`, borderRadius: 999, padding: "3px 10px", whiteSpace: "nowrap" }}>
          {c.pattern}
        </span>
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 700, color: vc, background: `${vc}1f`, borderRadius: 6, padding: "3px 9px" }}>
          Here: {hit.label}
        </span>
        <span style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.88)", lineHeight: 1.5 }}>{hit.plain}</span>
      </div>
      <button type="button" onClick={() => setOpen((o) => !o)}
        style={{ marginTop: 10, background: "none", border: "none", padding: 0, color: "rgba(0,229,255,0.8)", fontSize: "0.64rem", letterSpacing: "0.08em", cursor: "pointer" }}>
        {open ? "▾ Hide the numbers" : "▸ Show the numbers"}
      </button>
      {open && (
        <div style={{ marginTop: 6, fontSize: "0.7rem", color: "var(--text-dim)", lineHeight: 1.6 }}>
          Spearman ρ {c.rho > 0 ? "+" : ""}{c.rho.toFixed(2)} ({c.strength}) over {c.n.toLocaleString()} area-years in
          {" "}{c.year_pairs} pair{c.year_pairs === 1 ? "" : "s"} of years. {c.method}
        </div>
      )}
    </Card>
  );
}

// The sub-layers behind the tab's main value: the number, what it means here, how it is measured,
// and the cited source that explains it.
export function SupportingMeasures({ data }) {
  const rows = data?.supporting_measures || [];
  if (!rows.length) return <Muted>No supporting measurements for this area.</Muted>;
  return (
    <Card>
      <div style={{ display: "grid", gap: 0 }}>
        {rows.map((r, i) => (
          <div key={r.key} style={{ display: "grid", gridTemplateColumns: "minmax(150px, 1.1fr) 90px 2fr", gap: 14, alignItems: "baseline",
            padding: "11px 0", borderTop: i ? "1px solid rgba(255,255,255,0.06)" : "none" }}>
            <div>
              <div style={{ fontSize: "0.8rem", color: "white", fontWeight: 600 }}>{r.name}</div>
              <div style={{ fontSize: "0.62rem", color: "var(--text-dim)", marginTop: 3, lineHeight: 1.45 }}>{r.how}</div>
            </div>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.92rem", color: "#7cc8ff" }}>{r.display}</div>
            <div>
              <div style={{ fontSize: "0.78rem", color: "rgba(255,255,255,0.86)", lineHeight: 1.45 }}>
                {r.meaning ? r.meaning.charAt(0).toUpperCase() + r.meaning.slice(1) : "—"}
              </div>
              {r.source_title && (
                <div style={{ fontSize: "0.6rem", color: "var(--text-dim)", marginTop: 3, lineHeight: 1.4 }}>
                  Why it matters:{" "}
                  {r.url ? <a href={r.url} target="_blank" rel="noreferrer" style={{ color: "rgba(0,229,255,0.8)" }}>{r.source_title}</a> : r.source_title}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Muted({ children }) {
  return <div style={{ fontSize: "0.64rem", color: "rgba(200,214,229,0.55)", lineHeight: 1.55 }}>{children}</div>;
}

export function hasRelationships(data) {
  return (data?.relationships || []).some((r) => r.strength === "moderate" || r.strength === "strong"
    || (r.strength === "weak" && r.here && r.here.verdict !== "about typical"));
}

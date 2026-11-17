import { useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// ModelsPanel — city-wide model cards in plain words.
// Shown in the "Models & accuracy" tab of Deep Analysis. Data: GET /api/ml/summary
// (the same numbers the ML pipeline wrote to ml_summary.json — nothing computed here).
// ─────────────────────────────────────────────────────────────────────────────

const C = {
  heat: "#ff6a3d",
  outlier: "#ff3bd4",
  water: "#2ec5ff",
  air: "#ffb347",
  rel: "#7ad7ff",
  check: "#3ddc84",
  comp: "#ff5d73",
  dim: "rgba(200,214,229,0.62)",
  faint: "rgba(200,214,229,0.42)",
};

const LAYER_NAME = { ndvi: "Vegetation (NDVI)", lst: "Surface heat (LST)", water_health: "Water Health", aqi: "Air quality (AQI)" };

const fmt = (v, d = 2) => (v == null || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(d));
const signed = (v, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);

function Stat({ value, label, color = "white" }) {
  return (
    <div style={{ flex: 1, minWidth: 0, padding: "8px 10px", background: "rgba(0,0,0,0.28)", borderRadius: 6 }}>
      <div style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.15rem", fontWeight: 700, color, lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: "0.56rem", color: C.dim, marginTop: 3, lineHeight: 1.35 }}>{label}</div>
    </div>
  );
}

function Section({ n, title, what, accent, children }) {
  return (
    <section
      style={{
        padding: "14px 14px 12px",
        background: "rgba(255,255,255,0.02)",
        border: `1px solid ${accent}2e`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "0.6rem", color: accent }}>{n}</span>
        <h3 style={{ margin: 0, fontSize: "0.74rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "white", fontWeight: 600 }}>
          {title}
        </h3>
      </div>
      {what && <p style={{ margin: "6px 0 10px", fontSize: "0.68rem", lineHeight: 1.55, color: C.dim }}>{what}</p>}
      {children}
    </section>
  );
}

function Note({ children }) {
  return <p style={{ margin: "8px 0 0", fontSize: "0.62rem", lineHeight: 1.55, color: "rgba(255,255,255,0.78)" }}>{children}</p>;
}

function More({ label = "Details", children }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 8 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{ background: "none", border: "none", padding: 0, color: "rgba(0,229,255,0.85)", fontSize: "0.58rem", letterSpacing: "0.08em", cursor: "pointer" }}
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}

function Bar({ label, value, max, color, right }) {
  const w = max > 0 ? Math.max(2, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "118px 1fr 40px", gap: 8, alignItems: "center", fontSize: "0.6rem", marginTop: 5 }}>
      <span style={{ color: C.dim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={label}>{label}</span>
      <div style={{ height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3 }}>
        <div style={{ width: `${w}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ textAlign: "right", color: "white", fontFamily: "'DM Mono', monospace" }}>{right}</span>
    </div>
  );
}

// diverging bar for a correlation (-1..+1)
function RhoBar({ label, rho, strength, caution }) {
  const pct = Math.min(1, Math.abs(rho ?? 0)) * 50;
  const pos = (rho ?? 0) >= 0;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr 44px", gap: 8, alignItems: "center", fontSize: "0.6rem", marginTop: 6 }} title={caution || ""}>
      <span style={{ color: caution ? C.faint : C.dim }}>{label}{caution ? " *" : ""}</span>
      <div style={{ position: "relative", height: 8, background: "rgba(255,255,255,0.05)", borderRadius: 4 }}>
        <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "rgba(255,255,255,0.3)" }} />
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: pos ? "50%" : `${50 - pct}%`,
            width: `${pct}%`,
            background: pos ? "#ff8a66" : "#6ad6ff",
            borderRadius: 4,
            opacity: caution ? 0.5 : 1,
          }}
        />
      </div>
      <span style={{ textAlign: "right", fontFamily: "'DM Mono', monospace", color: "white" }} title={strength || ""}>{signed(rho)}</span>
    </div>
  );
}

export default function ModelsPanel({ summary }) {
  const s = summary || {};
  const x = s.xgboost_lst || {};
  const xm = x.metrics || {};
  const lif = s.layer_isolation_forest || {};
  const w = s.water_health || {};
  const st = s.station_isolation_forest || {};
  const rel = s.relationships?.pairs || [];
  // municipalities that have their own numbers in this city (Mumbai: Mumbai, Thane, Mira-Bhayandar)
  const munis = [...new Set(rel.flatMap((p) => Object.keys(p.by_municipality || {})))];
  const val = s.validation || {};
  const wc = val.worldcover || {};
  const aq = val.aqi_idw_loso || {};
  const comp = s.composite;
  const imp = Object.entries(x.feature_importance_gain || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <div style={{ fontSize: "0.66rem", color: C.dim, marginBottom: 12, lineHeight: 1.55 }}>
        City-wide results — not about the clicked location. Satellite snapshot {String(s.snapshot_at || "").slice(0, 10) || "–"}
        {s.cells_total ? ` · ${s.cells_total.toLocaleString()} cells of 300 m` : ""}.
      </div>
      <div style={{ display: "grid", gap: 14 }}>
        {!summary ? (
          <div style={{ fontSize: "0.7rem", color: C.dim }}>Model results appear after the ML pipeline has run (setup.ps1).</div>
        ) : (
          <>
            {/* 1 · Heat model */}
            {xm.r2_spatial_cv != null && (
              <Section
                n="01"
                title="Heat model · XGBoost"
                accent={C.heat}
                what="Predicts each cell's surface temperature from its land cover (vegetation, built-up, water). Cells much hotter than predicted are flagged as unexplained heat."
              >
                <div style={{ display: "flex", gap: 8 }}>
                  <Stat value={`${Math.round(xm.r2_spatial_cv * 100)}%`} label="of temperature differences explained (R²)" color={C.heat} />
                  <Stat value={`±${fmt(xm.rmse_c, 1)} °C`} label="typical error (RMSE)" />
                  <Stat value={x.flags?.unexplained_heat ?? "–"} label="cells hotter than land cover explains" color="#ff8a66" />
                </div>
                <Note>
                  Tested honestly: the city is cut into ~3 km blocks and each block is predicted by a model that never saw it.
                  {xm.linear_baseline_r2 != null && ` A simple straight-line model explains ${Math.round(xm.linear_baseline_r2 * 100)}%, so XGBoost adds a modest gain.`}
                </Note>
                {imp.length > 0 && (
                  <More label="What the model relies on most">
                    {imp.map(([k, v]) => (
                      <Bar key={k} label={k} value={v} max={imp[0][1]} color={C.heat} right={`${Math.round(v * 100)}%`} />
                    ))}
                    <div style={{ fontSize: "0.55rem", color: C.faint, marginTop: 6 }}>
                      Share of the model's splits (gain). Features: {xm.feature_set || "land cover"}.
                      {x.flags?.unexplained_cooling != null && ` ${x.flags.unexplained_cooling} cells are cooler than expected.`}
                    </div>
                  </More>
                )}
              </Section>
            )}

            {/* 2 · Isolation Forests */}
            {Object.keys(lif).length > 0 && (
              <Section
                n="02"
                title="Unusual cells · Isolation Forest"
                accent={C.outlier}
                what="For each layer, finds cells that look unlike the rest of the city (value, variability inside the cell, and contrast with the surrounding 1 km). About 5% are flagged by design."
              >
                <div style={{ display: "grid", gridTemplateColumns: "1fr 54px 54px 62px", gap: 6, fontSize: "0.52rem", letterSpacing: "0.08em", color: C.faint, paddingBottom: 4, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  <span>LAYER</span>
                  <span style={{ textAlign: "right" }}>CHECKED</span>
                  <span style={{ textAlign: "right" }}>FLAGGED</span>
                  <span style={{ textAlign: "right" }}>HIGH / LOW</span>
                </div>
                {["ndvi", "lst", "water_health", "aqi"].map((l) => {
                  const r = lif[l];
                  if (!r) return null;
                  const ok = r.status === "ok";
                  return (
                    <div key={l} style={{ display: "grid", gridTemplateColumns: "1fr 54px 54px 62px", gap: 6, fontSize: "0.64rem", padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.04)", fontFamily: "'DM Mono', monospace" }}>
                      <span style={{ fontFamily: "inherit", color: "white" }}>{LAYER_NAME[l]}</span>
                      {ok ? (
                        <>
                          <span style={{ textAlign: "right", color: C.dim }}>{r.eligible?.toLocaleString()}</span>
                          <span style={{ textAlign: "right", color: C.outlier }}>{r.anomalies}</span>
                          <span style={{ textAlign: "right", color: C.dim }}>{r.unusually_high} / {r.unusually_low}</span>
                        </>
                      ) : (
                        <span style={{ gridColumn: "span 3", textAlign: "right", color: C.faint }}>not enough data</span>
                      )}
                    </div>
                  );
                })}
                <Note>“Flagged” means unusual, not necessarily bad: a park inside a dense area is also unusual. The rest are “unusual pattern” (e.g. very mixed inside the cell).</Note>
              </Section>
            )}

            {/* 3 · Water Health */}
            {w.status === "ok" && (
              <Section
                n="03"
                title="Water Health baseline"
                accent={C.water}
                what="Compares every water cell with all water in the study region (robust z-score), so ‘low’ means worse than most local water — not a lab-grade water test."
              >
                <div style={{ display: "flex", gap: 8 }}>
                  <Stat value={w.eligible?.toLocaleString() ?? "–"} label="water cells scored" />
                  <Stat value={fmt(w.median, 3)} label="typical (median) index, 0–1" color={C.water} />
                  <Stat value={w.flags?.low_water_condition ?? "–"} label="cells clearly below the rest" color="#ff8a66" />
                </div>
              </Section>
            )}

            {/* 4 · Air stations */}
            <Section
              n="04"
              title="Air quality · stations"
              accent={C.air}
              what="AQI comes only from official CPCB-network stations (via OpenAQ, readings ≤ 48 h old). Between stations it is interpolated, so it is an estimate."
            >
              <div style={{ display: "flex", gap: 8 }}>
                <Stat value={st.status === "ok" ? st.eligible : "–"} label="stations compared" />
                <Stat value={st.status === "ok" ? st.anomalies : "–"} label="with an unusual pollutant mix" color={C.air} />
                <Stat value={aq.status === "ok" ? `±${fmt(aq.mae, 0)}` : "–"} label="AQI error when a station is hidden and predicted" color={aq.status === "ok" && aq.mae > 50 ? "#ff8a66" : "white"} />
              </div>
              {aq.status === "ok" ? (
                <Note>
                  With few stations, AQI between them is a rough estimate (held-out error ±{fmt(aq.mae, 0)} AQI points
                  {aq.category_agreement_pct != null ? `; same CPCB category ${aq.category_agreement_pct}% of the time` : ""}).
                  That is why each map cell carries a reliability label.
                </Note>
              ) : (
                <Note>The interpolation check runs when a current station surface exists.</Note>
              )}
              {st.status === "ok" && (st.stations || []).some((r) => r.is_anomaly) && (
                <More label="Which stations are unusual">
                  {(st.stations || []).filter((r) => r.is_anomaly).slice(0, 6).map((r) => (
                    <div key={r.station_name} style={{ fontSize: "0.6rem", color: "#ffd9a8", marginTop: 3 }}>
                      • {r.station_name}: {(r.dominant_deviations || []).slice(0, 2).map((d) => `${d.pollutant} ${signed(d.z, 1)}σ`).join(", ")}
                    </div>
                  ))}
                </More>
              )}
            </Section>

            {/* 5 · Relationships */}
            {rel.length > 0 && (
              <Section
                n="05"
                title="How the indicators move together"
                accent={C.rel}
                what="Rank correlation (Spearman ρ) across all cells: −1 = one rises as the other falls, +1 = they rise together. Associations, not causes."
              >
                {rel.map((p) => (
                  <RhoBar key={p.label} label={p.label} rho={p.all?.spearman_rho} strength={p.all?.strength} caution={p.caution} />
                ))}
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.52rem", color: C.faint, marginTop: 4, paddingLeft: 158, paddingRight: 52 }}>
                  <span>−1</span><span>0</span><span>+1</span>
                </div>
                {munis.length > 1 && (
                <More label="By municipality">
                  <div style={{ display: "grid", gridTemplateColumns: `1fr ${munis.map(() => "46px").join(" ")}`, gap: 4, fontSize: "0.52rem", color: C.faint }}>
                    <span>PAIR</span>
                    {munis.map((m) => <span key={m} style={{ textAlign: "right" }}>{m === "Mira-Bhayandar" ? "MBMC" : m.toUpperCase()}</span>)}
                  </div>
                  {rel.map((p) => (
                    <div key={p.label} style={{ display: "grid", gridTemplateColumns: `1fr ${munis.map(() => "46px").join(" ")}`, gap: 4, fontSize: "0.6rem", padding: "2px 0", fontFamily: "'DM Mono', monospace", color: "white" }}>
                      <span style={{ fontFamily: "inherit" }}>{p.label}</span>
                      {munis.map((m) => <span key={m} style={{ textAlign: "right" }}>{signed(p.by_municipality?.[m]?.spearman_rho)}</span>)}
                    </div>
                  ))}
                  <div style={{ fontSize: "0.55rem", color: C.faint, marginTop: 6, lineHeight: 1.5 }}>
                    Effect sizes only: neighbouring cells are not independent, so no p-values are claimed. * involves interpolated AQI.
                  </div>
                </More>
                )}
              </Section>
            )}

            {/* 6 · Validation */}
            <Section
              n="06"
              title="Checked against independent data"
              accent={C.check}
              what="Our land-cover shares are compared with ESA WorldCover 2021 (10 m), a map we did not use to build the layers."
            >
              {wc.status === "ok" ? (
                <>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Stat value={`${fmt(wc.dominant_class_agreement_pct, 1)}%`} label="cells where the main land cover agrees" color={C.check} />
                    <Stat value={wc.lst_physically_plausible ? "Yes ✓" : wc.lst_physically_plausible === false ? "No ✗" : "–"} label="built-up land hotter than trees and water" />
                  </div>
                  {Object.keys(wc.lst_by_worldcover_class || {}).length > 0 && (
                    <More label="Median surface temperature by land cover">
                      {Object.entries(wc.lst_by_worldcover_class)
                        .sort((a, b) => b[1].median_c - a[1].median_c)
                        .map(([k, v], _, arr) => (
                          <Bar key={k} label={k} value={v.median_c - (arr[arr.length - 1][1].median_c - 1)} max={arr[0][1].median_c - (arr[arr.length - 1][1].median_c - 1)} color={C.heat} right={`${fmt(v.median_c, 1)}°`} />
                        ))}
                      {wc.caveat && <div style={{ fontSize: "0.55rem", color: C.faint, marginTop: 6, lineHeight: 1.5 }}>{wc.caveat}</div>}
                    </More>
                  )}
                </>
              ) : (
                <Note>Not run yet — needs Earth Engine ({wc.how || "scripts/build_validation_reference.py"}).</Note>
              )}
            </Section>

            {/* 7 · Composite */}
            {comp && (
              <Section
                n="07"
                title="Composite stress · method"
                accent={C.comp}
                what="A GeoSense-derived index (not an official one): heat, surface condition (vegetation on land, Water Health on water) and air, each scaled 0–1, combined only where at least 2 of 3 exist."
              >
                {["heat", "surface", "air"].map((k) => (
                  <Bar key={k} label={{ heat: "Heat (LST)", surface: "Surface condition", air: "Air (AQI)" }[k]} value={comp.weights?.[k] ?? 0} max={0.4} color={C.comp} right={fmt(comp.weights?.[k], 2)} />
                ))}
                {comp.sensitivity?.summary && <Note>Robustness: {comp.sensitivity.summary}</Note>}
              </Section>
            )}

            <div style={{ fontSize: "0.58rem", color: C.faint, lineHeight: 1.6, padding: "2px 4px 8px" }}>
              All results come from one satellite snapshot. They show statistical patterns and associations, not proof of what causes them.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

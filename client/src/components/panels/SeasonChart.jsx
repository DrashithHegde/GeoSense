import { useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// SeasonChart — "Over time" for one location, year by year: the cell's value in every
// pre-monsoon (Mar–May) and post-monsoon (Oct–Dec) season since 2023 as two lines (one per
// season), plus the same-season change vs last year.
// Values come from GET /api/analysis/point/explain → evidence.history (cell_history table).
// Missing seasons stay missing (no cloud-free image) — nothing is filled or interpolated.
// ─────────────────────────────────────────────────────────────────────────────

const KIND = {
  pre: { color: "#ffb347", name: "Pre-monsoon", months: "Mar–May" },
  post: { color: "#5ad1ff", name: "Post-monsoon", months: "Oct–Dec" },
};

// which direction is a concern, and what counts as a meaningful change (matches the backend)
const METRIC_INFO = {
  lst: {
    name: "Surface temperature",
    unit: "°C",
    worse: "up",
    digits: 1,
    minSpan: 1.5,
  },
  ndvi: {
    name: "Vegetation (NDVI)",
    unit: "",
    worse: "down",
    digits: 2,
    minSpan: 0.06,
  },
  wh: {
    name: "Water Health",
    unit: "",
    worse: "down",
    digits: 2,
    minSpan: 0.04,
  },
  aqi: { name: "AQI (station)", unit: "", worse: "up", digits: 0, minSpan: 20 },
};

const FOCUS_TO_METRIC = {
  lst: "lst",
  ndvi: "ndvi",
  water_health: "wh",
  aqi: "aqi",
};

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || 1;
  const raw = span / (count - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const start = Math.floor(lo / step) * step;
  const ticks = [];
  for (let v = start; v <= hi + step * 0.5 && ticks.length < 8; v += step)
    ticks.push(+v.toFixed(6));
  return ticks;
}

// Year-by-year chart: one x position per year, one line per season type (pre-monsoon and
// post-monsoon), so each line compares the SAME season across years (a plain yearly average
// would mix cloud-free months that differ by season). Missing seasons stay gaps.
function Chart({ series, info, missingText }) {
  const W = 560,
    H = 230,
    L = 52,
    R = 16,
    T = 30,
    B = 40,
    PADX = 34,
    OFF = 7;
  const years = [...new Set(series.map((p) => p.year))].sort((a, b) => a - b);
  const vals = series.map((p) => p.value).filter((v) => v != null);
  if (vals.length < 2 || years.length < 1) return null;
  let lo = Math.min(...vals),
    hi = Math.max(...vals);
  if (hi - lo < info.minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - info.minSpan / 2;
    hi = mid + info.minSpan / 2;
  }
  const ticks = niceTicks(lo, hi);
  const y0 = Math.min(lo, ticks[0]);
  const y1 = Math.max(hi, ticks[ticks.length - 1]);
  const nY = years.length;
  const xYear = (yr) => {
    const i = years.indexOf(yr);
    return nY === 1
      ? (L + W - R) / 2
      : L + PADX + (i * (W - L - R - 2 * PADX)) / (nY - 1);
  };
  const x = (p) => xYear(p.year) + (p.kind === "pre" ? -OFF : OFF);
  const y = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
  const fmt = (v) =>
    info.digits === 0 ? Math.round(v) : v.toFixed(info.digits);
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
  const tickFmt = (v) =>
    Number.isInteger(+step.toFixed(6))
      ? Math.round(v)
      : v.toFixed(step >= 0.1 ? 1 : 2);

  const byKind = (k) =>
    series.filter((p) => p.kind === k).sort((a, b) => a.year - b.year);
  const lines = ["pre", "post"].map((k) => {
    const all = byKind(k);
    const pts = all.filter((p) => p.value != null);
    const segs = [];
    for (let j = 1; j < pts.length; j += 1) {
      const a = pts[j - 1],
        b = pts[j];
      // dashed when a year of this season is missing in between, or the newer one is still in progress
      const gap = all.some((p) => p.year > a.year && p.year < b.year);
      segs.push({ a, b, dashed: gap || b.partial });
    }
    return { k, segs };
  });

  // value labels: when both seasons of a year have values, the higher point's label goes above
  // and the lower one's below, so they never overlap
  const labelBelow = new Set();
  years.forEach((yr) => {
    const pre = series.find(
      (p) => p.year === yr && p.kind === "pre" && p.value != null,
    );
    const post = series.find(
      (p) => p.year === yr && p.kind === "post" && p.value != null,
    );
    if (pre && post && Math.abs(y(pre.value) - y(post.value)) < 22) {
      labelBelow.add((y(pre.value) > y(post.value) ? pre : post).season);
    }
  });

  const colW = nY === 1 ? 120 : (W - L - R - 2 * PADX) / (nY - 1);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={`${info.name} year by year`}
      style={{ display: "block" }}
    >
      {years.map((yr, k) => (
        <g key={yr}>
          {k % 2 === 0 && (
            <rect
              x={Math.max(L, xYear(yr) - colW / 2)}
              y={T - 10}
              width={Math.min(colW, W - R - Math.max(L, xYear(yr) - colW / 2))}
              height={H - T - B + 10}
              fill="rgba(255,255,255,0.03)"
            />
          )}
          <text
            x={xYear(yr)}
            y={H - 12}
            fontSize="12"
            fill="rgba(255,255,255,0.82)"
            textAnchor="middle"
            fontFamily="'DM Mono', monospace"
          >
            {yr}
          </text>
        </g>
      ))}

      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={L}
            x2={W - R}
            y1={y(t)}
            y2={y(t)}
            stroke="rgba(255,255,255,0.08)"
          />
          <text
            x={L - 8}
            y={y(t) + 3.5}
            fontSize="10"
            fill="rgba(200,214,229,0.6)"
            textAnchor="end"
            fontFamily="'DM Mono', monospace"
          >
            {tickFmt(t)}
            {info.unit === "°C" ? "°" : ""}
          </text>
        </g>
      ))}

      {lines.map((l) =>
        l.segs.map((sg, j) => (
          <line
            key={`${l.k}${j}`}
            x1={x(sg.a)}
            y1={y(sg.a.value)}
            x2={x(sg.b)}
            y2={y(sg.b.value)}
            stroke={KIND[l.k].color}
            strokeWidth="2.4"
            strokeDasharray={sg.dashed ? "5 4" : undefined}
            opacity="0.92"
          />
        )),
      )}

      {series.map((p) => {
        const c = KIND[p.kind]?.color || "#ccc";
        if (p.value == null) {
          return (
            <g key={p.season}>
              <text
                x={x(p)}
                y={H - B - 6}
                fontSize="10"
                fill={c}
                opacity="0.55"
                textAnchor="middle"
              >
                ✕<title>{`${p.label}: ${missingText} — left missing`}</title>
              </text>
            </g>
          );
        }
        const below = labelBelow.has(p.season);
        return (
          <g key={p.season}>
            <circle
              cx={x(p)}
              cy={y(p.value)}
              r="5"
              fill={p.partial ? "#0b0f14" : c}
              stroke={c}
              strokeWidth="2"
            >
              <title>{`${p.label}: ${fmt(p.value)}${info.unit ? " " + info.unit : ""}${p.partial ? " (season in progress)" : ""}`}</title>
            </circle>
            <text
              x={x(p)}
              y={below ? y(p.value) + 18 : y(p.value) - 10}
              fontSize="10.5"
              fill={c}
              textAnchor="middle"
              fontFamily="'DM Mono', monospace"
            >
              {fmt(p.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ChangeCallout({ change, info, regionNote = true }) {
  if (!change) return null;
  const d = change.delta;
  const up = d > 0;
  const worse = (info.worse === "up" && up) || (info.worse === "down" && !up);
  const tiny = Math.abs(d) < info.minSpan / 6;
  const color = tiny ? "rgba(255,255,255,0.85)" : worse ? "#ff8a66" : "#3ddc84";
  // "sudden" is only computed for satellite cells (vs the city-wide change); stations get no verdict on it
  const judged = typeof change.sudden === "boolean";
  const verdict = change.sudden
    ? "Sudden change — much larger than the change across the rest of the city over the same period"
    : tiny
      ? "Practically no change"
      : judged
        ? `${worse ? "Worse" : "Better"} than last year, but within the usual year-to-year variation across the city`
        : `${worse ? "Worse" : "Better"} than the same season last year`;
  const matched = /matched/i.test(change.from || "");
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        alignItems: "center",
        padding: "10px 12px",
        background: "rgba(0,0,0,0.28)",
        borderRadius: 8,
        border: `1px solid ${change.sudden ? "rgba(255,138,102,0.5)" : "rgba(255,255,255,0.08)"}`,
      }}
    >
      <div style={{ textAlign: "center", minWidth: 104, whiteSpace: "nowrap" }}>
        <div
          style={{
            fontFamily: "'Syne', sans-serif",
            fontSize: "1.45rem",
            fontWeight: 700,
            color,
            lineHeight: 1,
          }}
        >
          {tiny ? "≈ " : up ? "▲ " : "▼ "}
          {up ? "+" : ""}
          {info.digits === 0 ? Math.round(d) : d.toFixed(info.digits)}
          {info.unit === "°C" ? (
            <span style={{ fontSize: "0.75rem" }}>°C</span>
          ) : null}
        </div>
        <div
          style={{
            fontSize: "0.52rem",
            color: "rgba(200,214,229,0.6)",
            marginTop: 4,
            letterSpacing: "0.08em",
          }}
        >
          VS LAST YEAR
        </div>
      </div>
      <div
        style={{
          fontSize: "0.68rem",
          lineHeight: 1.55,
          color: "rgba(255,255,255,0.85)",
        }}
      >
        <div style={{ color, fontWeight: 600 }}>{verdict}</div>
        <div style={{ color: "rgba(200,214,229,0.65)" }}>
          {change.to} compared with {change.from}
          {regionNote &&
            change.region_median_delta != null &&
            ` · city-wide typical change ${change.region_median_delta > 0 ? "+" : ""}${info.digits === 0 ? Math.round(change.region_median_delta) : change.region_median_delta.toFixed(info.digits)}`}
        </div>
        {regionNote &&
          change.region_median_delta != null &&
          Math.abs(change.region_median_delta) >=
            (info.unit === "°C" ? 2 : info.minSpan) &&
          !change.sudden && (
            <div
              style={{ color: "rgba(255,214,120,0.85)", fontSize: "0.6rem" }}
            >
              The whole city shifted by about as much, so most of this reflects
              different conditions on the image dates (weather, soil moisture),
              not a change on the ground. Relative to the city:{" "}
              {d - change.region_median_delta > 0 ? "+" : ""}
              {info.digits === 0
                ? Math.round(d - change.region_median_delta)
                : (d - change.region_median_delta).toFixed(info.digits)}
              {info.unit === "°C" ? " °C" : ""}.
            </div>
          )}
        {matched && (
          <div style={{ color: "rgba(200,214,229,0.5)", fontSize: "0.6rem" }}>
            The season in progress is compared with the same dates last year, so
            this can differ from the full-season point on the chart.
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ missingText }) {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "4px 14px",
        fontSize: "0.58rem",
        color: "rgba(200,214,229,0.7)",
        marginBottom: 4,
      }}
    >
      {Object.entries(KIND).map(([k, v]) => (
        <span key={k}>
          <span style={{ color: v.color }}>━●</span> {v.name} ({v.months}), year
          to year
        </span>
      ))}
      <span>○ season still in progress</span>
      <span>✕ {missingText}</span>
    </div>
  );
}

function Facts({ entry, info }) {
  const ps = entry.persistence;
  const tr = entry.trend || {};
  const bits = [];
  if (ps && ps.seasons_observed) {
    bits.push({
      strong: ps.persistent,
      text:
        ps.seasons_flagged > 0
          ? `In the city's ${ps.description} in ${ps.seasons_flagged} of ${ps.seasons_observed} seasons${ps.persistent ? " — a persistent pattern" : ""}`
          : `Never in the city's ${ps.description} (${ps.seasons_observed} seasons checked)`,
    });
  }
  ["pre", "post"].forEach((k) => {
    if (tr[k]) {
      const v = tr[k].per_year;
      bits.push({
        text: `${KIND[k].name} trend ${v > 0 ? "+" : ""}${info.digits === 0 ? Math.round(v) : v.toFixed(info.digits === 1 ? 2 : 3)}${info.unit ? " " + info.unit : ""} per year (${tr[k].seasons} seasons, indicative only)`,
      });
    }
  });
  if (!bits.length) return null;
  return (
    <div style={{ display: "grid", gap: 4, marginTop: 8 }}>
      {bits.map((b, i) => (
        <div
          key={i}
          style={{
            fontSize: "0.66rem",
            lineHeight: 1.5,
            color: b.strong ? "#ffd23c" : "rgba(255,255,255,0.78)",
            display: "flex",
            gap: 8,
          }}
        >
          <span style={{ color: b.strong ? "#ffd23c" : "rgba(0,229,255,0.7)" }}>
            ■
          </span>
          <span>{b.text}</span>
        </div>
      ))}
    </div>
  );
}

export default function SeasonChart({ history, focus }) {
  const available = ["lst", "ndvi", "wh"].filter((m) => history?.metrics?.[m]);
  const initial = FOCUS_TO_METRIC[focus] || "lst";
  const [pick, setPick] = useState(null);
  if (!history) {
    return (
      <Empty text="Seasonal history has not been built yet (setup.ps1 -History)." />
    );
  }

  // AQI: nearest station's seasonal median
  if (focus === "aqi") {
    const st = history.station;
    if (!st?.series?.some((p) => p.aqi_median != null)) {
      return (
        <Empty text="No monitoring station with enough daily data within 10 km of this point." />
      );
    }
    const seasonsMeta = Object.fromEntries(
      (history.seasons || []).map((s) => [s.season, s]),
    );
    const series = st.series.map((p) => ({
      ...p,
      kind:
        seasonsMeta[p.season]?.kind ||
        (p.label.startsWith("Pre") ? "pre" : "post"),
      year:
        seasonsMeta[p.season]?.year ||
        Number((p.label.match(/\d{4}/) || [])[0]),
      value: p.aqi_median,
    }));
    const info = METRIC_INFO.aqi;
    return (
      <div>
        <div
          style={{
            fontSize: "0.66rem",
            color: "rgba(255,255,255,0.8)",
            marginBottom: 6,
          }}
        >
          Station <b>{st.station_name}</b> ({(st.distance_m / 1000).toFixed(1)}{" "}
          km away) · seasonal median of daily AQI
        </div>
        <Legend missingText="no station data" />
        <Chart series={series} info={info} missingText="no station data" />
        {st.change && (
          <ChangeCallout change={st.change} info={info} regionNote={false} />
        )}
        <div
          style={{
            fontSize: "0.56rem",
            color: "rgba(200,214,229,0.45)",
            marginTop: 6,
          }}
        >
          24-hour pollutants only (PM2.5, PM10, NO₂, SO₂, NH₃ where reported);
          O₃ and CO need 8-hour maxima that daily data does not have.
        </div>
      </div>
    );
  }

  const metric =
    pick && available.includes(pick)
      ? pick
      : available.includes(initial)
        ? initial
        : available[0];
  const entry = history.metrics?.[metric];
  if (!entry)
    return <Empty text="No cloud-free seasonal data for this layer here." />;
  const info = METRIC_INFO[metric];

  return (
    <div>
      {focus === "composite" && available.length > 1 && (
        <div
          style={{ display: "flex", gap: 6, marginBottom: 8 }}
          role="tablist"
          aria-label="Indicator"
        >
          {available.map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={m === metric}
              onClick={() => setPick(m)}
              style={{
                padding: "4px 10px",
                borderRadius: 12,
                fontSize: "0.6rem",
                cursor: "pointer",
                background:
                  m === metric
                    ? "rgba(0,229,255,0.14)"
                    : "rgba(255,255,255,0.03)",
                border: `1px solid ${m === metric ? "rgba(0,229,255,0.5)" : "rgba(255,255,255,0.1)"}`,
                color: m === metric ? "#00e5ff" : "rgba(200,214,229,0.7)",
              }}
            >
              {METRIC_INFO[m].name}
            </button>
          ))}
        </div>
      )}
      <Legend missingText="no cloud-free image" />
      <Chart
        series={entry.series}
        info={info}
        missingText="no cloud-free image"
      />
      <ChangeCallout change={entry.change} info={info} />
      <Facts entry={entry} info={info} />
    </div>
  );
}

function Empty({ text }) {
  return (
    <div
      style={{
        fontSize: "0.68rem",
        color: "rgba(200,214,229,0.55)",
        fontStyle: "italic",
      }}
    >
      {text}
    </div>
  );
}

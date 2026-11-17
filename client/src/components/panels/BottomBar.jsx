import { CITY_CONFIG } from "../../constants/cities";

const AQI_COLORS = {
  good: "#00A859",
  satisfactory: "#8CC63F",
  moderate: "#FFF200",
  poor: "#F7931E",
  veryPoor: "#ED1C24",
  severe: "#9E0B0F",
};

const AQI_COLOR_STOPS = [
  { value: 0, color: AQI_COLORS.good },
  { value: 50, color: AQI_COLORS.good },
  { value: 50, color: AQI_COLORS.satisfactory },
  { value: 100, color: AQI_COLORS.satisfactory },
  { value: 100, color: AQI_COLORS.moderate },
  { value: 200, color: AQI_COLORS.moderate },
  { value: 200, color: AQI_COLORS.poor },
  { value: 300, color: AQI_COLORS.poor },
  { value: 300, color: AQI_COLORS.veryPoor },
  { value: 400, color: AQI_COLORS.veryPoor },
  { value: 400, color: AQI_COLORS.severe },
  { value: 500, color: AQI_COLORS.severe },
];

const DEFAULT_NDVI_STOPS = [
  { value: 0.0, label: "Bare / built", rgb: [86, 66, 52] },
  { value: 0.1, label: "Very sparse", rgb: [128, 94, 62] },
  { value: 0.2, label: "Sparse", rgb: [176, 140, 76] },
  { value: 0.35, label: "Light", rgb: [218, 200, 96] },
  { value: 0.5, label: "Moderate", rgb: [150, 208, 76] },
  { value: 0.65, label: "Dense", rgb: [60, 188, 84] },
  { value: 0.8, label: "Very dense", rgb: [24, 150, 78] },
];

const DEFAULT_WATER_STOPS = [
  { display_value: 0, value: 0.146, label: "Low", rgb: [5, 42, 58] },
  { display_value: 0.25, value: 0.441, label: "Medium-low", rgb: [4, 82, 126] },
  { display_value: 0.5, value: 0.459, label: "Medium", rgb: [0, 138, 184] },
  {
    display_value: 0.75,
    value: 0.472,
    label: "Medium-high",
    rgb: [0, 192, 220],
  },
  { display_value: 1, value: 0.6, label: "High", rgb: [30, 232, 238] },
];

const DEFAULT_LST_STOPS = [
  { position: 0, temperature_c: 25, label: "Coolest", color: "#342696" },
  { position: 0.17, temperature_c: 30, label: "Cool", color: "#621ea2" },
  { position: 0.33, temperature_c: 33, label: "Mild", color: "#982296" },
  { position: 0.5, temperature_c: 34, label: "Warm", color: "#ce3a70" },
  { position: 0.67, temperature_c: 36, label: "Hot", color: "#ee6548" },
  { position: 0.83, temperature_c: 39, label: "Very hot", color: "#fa9d34" },
  { position: 1, temperature_c: 44, label: "Hottest", color: "#fdde5e" },
];

const COMPOSITE_STOPS = [
  { value: 0, color: "#205c78" },
  { value: 17, color: "#268c8a" },
  { value: 33, color: "#6eaa78" },
  { value: 50, color: "#d6c45c" },
  { value: 67, color: "#f4903e" },
  { value: 83, color: "#e2463c" },
  { value: 100, color: "#b01e60" },
];

function rgbToHex(rgb) {
  return `#${rgb.map((channel) => Math.round(channel).toString(16).padStart(2, "0")).join("")}`;
}

function numericLabel(value, digits = 2) {
  return Number(value).toFixed(digits);
}

function getLayerLegendConfig(
  layerId,
  { aqiSurface, ndviSurface, waterHealthSurface, lstSurface, compositeSurface },
) {
  if (layerId === "aqi") {
    if (!aqiSurface) return null;
    // same colours as the AQI heatmap (from the surface manifest), else the built-in CPCB set
    const aqiStops = aqiSurface?.visualization?.stops;
    if (aqiStops?.length) {
      return {
        valueStops: [[0, 0], [500, 100]],
        stops: aqiStops.map((stop) => ({ position: (Number(stop.value) / 500) * 100, color: stop.color })),
        minimumLabel: "0 Good",
        maximumLabel: "500 Severe",
        minimumColor: aqiStops[0].color,
        maximumColor: aqiStops.at(-1).color,
      };
    }
    return {
      valueStops: [[0, 0], [500, 100]],
      stops: AQI_COLOR_STOPS.map(({ value, color }) => ({
        position: (value / 500) * 100,
        color,
      })),
      minimumLabel: "0 Good",
      maximumLabel: "500 Severe",
      minimumColor: AQI_COLORS.good,
      maximumColor: AQI_COLORS.severe,
    };
  }

  if (layerId === "ndvi") {
    const stops = ndviSurface?.visualization?.stops || DEFAULT_NDVI_STOPS;
    const firstValue = Number(stops[0]?.value ?? 0.05);
    const lastValue = Number(stops.at(-1)?.value ?? 0.8);
    const span = Math.max(lastValue - firstValue, Number.EPSILON);
    const rgbStops = stops.map((stop) => ({
      position: ((Number(stop.value) - firstValue) / span) * 100,
      color: Array.isArray(stop.rgb) ? rgbToHex(stop.rgb) : stop.color,
    }));
    return {
      valueStops: [[firstValue, 0], [lastValue, 100]],
      stops: rgbStops,
      minimumLabel: ndviSurface?.visualization?.legend?.left_label || "LOW",
      maximumLabel: ndviSurface?.visualization?.legend?.right_label || "HIGH",
      minimumColor: rgbStops[0]?.color,
      maximumColor: rgbStops.at(-1)?.color,
    };
  }

  if (layerId === "water_health") {
    const visualization = waterHealthSurface?.visualization;
    const stops = visualization?.stops || DEFAULT_WATER_STOPS;
    const range = visualization?.legend?.range;
    const colors = stops.map((stop) =>
      Array.isArray(stop.rgb) ? rgbToHex(stop.rgb) : stop.color,
    );
    return {
      valueStops: stops.map((stop) => [Number(stop.value), Number(stop.display_value ?? stop.position ?? 0) * 100]),
      stops: stops.map((stop) => ({
        position: Number(stop.display_value ?? stop.position ?? 0) * 100,
        color: Array.isArray(stop.rgb) ? rgbToHex(stop.rgb) : stop.color,
      })),
      minimumLabel:
        visualization?.legend?.left_label ||
        `LOW · ${numericLabel(range?.min ?? stops[0]?.value ?? 0, 3)}`,
      maximumLabel:
        visualization?.legend?.right_label ||
        `HIGH · ${numericLabel(range?.max ?? stops.at(-1)?.value ?? 1, 3)}`,
      minimumColor: colors[0],
      maximumColor: colors.at(-1),
    };
  }

  if (layerId === "lst") {
    const stops = lstSurface?.visualization?.color_stops || DEFAULT_LST_STOPS;
    const minimum = Number(stops[0]?.temperature_c ?? -1.2);
    const maximum = Number(stops.at(-1)?.temperature_c ?? 51);
    return {
      valueStops: stops.map((stop) => [Number(stop.temperature_c), Number(stop.position) * 100]),
      stops: stops.map((stop) => ({
        position: Number(stop.position) * 100,
        color: stop.color,
      })),
      minimumLabel: `${numericLabel(minimum, 1)}°C`,
      maximumLabel: `${numericLabel(maximum, 1)}°C`,
      minimumColor: stops[0]?.color,
      maximumColor: stops.at(-1)?.color,
    };
  }

  const compStops = compositeSurface?.visualization?.stops;
  if (compStops?.length) {
    return {
      // composite score 0-1 (the knots the map was coloured with)
      valueStops: compStops.map((stop) => [Number(stop.value), Number(stop.position) * 100]),
      stops: compStops.map((stop) => ({ position: Number(stop.position) * 100, color: stop.color })),
      minimumLabel: compositeSurface.visualization?.legend?.left_label || "LOW STRESS",
      maximumLabel: compositeSurface.visualization?.legend?.right_label || "HIGH STRESS",
      minimumColor: compStops[0].color,
      maximumColor: compStops.at(-1).color,
    };
  }
  return {
    valueStops: [[0, 0], [1, 100]],
    stops: COMPOSITE_STOPS.map((stop) => ({
      position: stop.value,
      color: stop.color,
    })),
    minimumLabel: "LOW STRESS",
    maximumLabel: "HIGH STRESS",
    minimumColor: COMPOSITE_STOPS[0].color,
    maximumColor: COMPOSITE_STOPS.at(-1).color,
  };
}

// Where a value sits on the legend: piecewise-linear between the legend's own stops, so the
// pointer lands on the colour the map uses for that value. Clamped to the bar's ends.
function legendPosition(config, value) {
  const vs = (config?.valueStops || []).filter(([v, p]) => Number.isFinite(v) && Number.isFinite(p))
    .sort((a, b) => a[0] - b[0]);
  if (value == null || !Number.isFinite(Number(value)) || vs.length < 2) return null;
  const v = Number(value);
  if (v <= vs[0][0]) return vs[0][1];
  if (v >= vs.at(-1)[0]) return vs.at(-1)[1];
  for (let i = 1; i < vs.length; i += 1) {
    const [v0, p0] = vs[i - 1];
    const [v1, p1] = vs[i];
    if (v <= v1) return v1 === v0 ? p1 : p0 + ((v - v0) / (v1 - v0)) * (p1 - p0);
  }
  return null;
}

function SeverityLegend({ config, marker = null }) {
  if (!config) return null;
  const at = legendPosition(config, marker);
  const gradient = config.stops
    .map((stop) => `${stop.color} ${stop.position}%`)
    .join(", ");

  return (
    <div
      className="glass-sharp"
      style={{
        maxWidth: 560,
        margin: "0 auto 10px",
        padding: "8px 18px 10px",
      }}
    >
      <div style={{ position: "relative" }}>
        <div
          className="severity-gradient-bar"
          role="img"
          aria-label={`${config.minimumLabel} to ${config.maximumLabel}`}
          style={{
            background: `linear-gradient(to right, ${gradient})`,
            marginBottom: 5,
          }}
        />
        {at != null && (
          // the clicked area's place on this scale
          <div
            className="legend-pointer"
            aria-label="Selected location on this scale"
            style={{ left: `${Math.max(0, Math.min(100, at))}%` }}
          />
        )}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.52rem",
          letterSpacing: "0.12em",
          color: "var(--text-dim)",
          textTransform: "uppercase",
        }}
      >
        <span style={{ color: config.minimumColor }}>
          ● {config.minimumLabel}
        </span>
        <span style={{ color: config.maximumColor }}>
          {config.maximumLabel} ●
        </span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CitySelector
// Row of pill buttons for selecting the active city
// ─────────────────────────────────────────────────────────────────────────────

function CitySelector({ activeCity, onSelect }) {
  const isIndiaActive = !activeCity;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
      }}
    >
      <button
        onClick={() => onSelect("india")}
        style={{
          padding: "6px 18px",
          background: isIndiaActive
            ? "rgba(0,229,255,0.1)"
            : "rgba(11,15,20,0.72)",
          backdropFilter: "blur(16px)",
          border: isIndiaActive
            ? "1px solid rgba(0,229,255,0.42)"
            : "1px solid rgba(0,229,255,0.12)",
          borderRadius: 4,
          color: isIndiaActive
            ? "rgba(0,229,255,0.9)"
            : "rgba(200,214,229,0.45)",
          fontFamily: "'DM Mono', monospace",
          fontSize: "0.62rem",
          lineHeight: 1.35,
          letterSpacing: "0.14em",
          cursor: "pointer",
          textTransform: "uppercase",
          boxShadow: isIndiaActive
            ? "0 0 18px rgba(0,229,255,0.18), inset 0 0 8px rgba(0,229,255,0.06)"
            : "none",
          transition: "all 0.25s ease",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {isIndiaActive && (
          <span
            style={{
              display: "inline-block",
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "#00e5ff",
              boxShadow: "0 0 6px #00e5ff",
              flexShrink: 0,
            }}
          />
        )}
        Pan-India
      </button>

      {Object.values(CITY_CONFIG).map((city) => {
        const isActive = activeCity === city.id;

        return (
          <button
            key={city.id}
            onClick={() => onSelect(city.id)}
            style={{
              padding: "6px 18px",
              background: isActive
                ? "rgba(0,229,255,0.1)"
                : "rgba(11,15,20,0.72)",
              backdropFilter: "blur(16px)",
              border: isActive
                ? "1px solid rgba(0,229,255,0.42)"
                : "1px solid rgba(0,229,255,0.12)",
              borderRadius: 4,
              color: isActive
                ? "rgba(0,229,255,0.9)"
                : "rgba(200,214,229,0.45)",
              fontFamily: "'DM Mono', monospace",
              fontSize: "0.62rem",
              lineHeight: 1.35,
              letterSpacing: "0.14em",
              cursor: "pointer",
              textTransform: "uppercase",
              boxShadow: isActive
                ? "0 0 18px rgba(0,229,255,0.18), inset 0 0 8px rgba(0,229,255,0.06)"
                : "none",
              transition: "all 0.25s ease",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {isActive && (
              <span
                style={{
                  display: "inline-block",
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "#00e5ff",
                  boxShadow: "0 0 6px #00e5ff",
                  flexShrink: 0,
                }}
              />
            )}
            {city.label}
          </button>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BottomBar
// Fixed bottom panel containing legend + city selector
// ─────────────────────────────────────────────────────────────────────────────

export default function BottomBar({
  activeCity,
  onSelectCity,
  activeLayers,
  ndviSurface,
  waterHealthSurface,
  lstSurface,
  aqiSurface,
  compositeSurface,
  markerValue = null,
}) {
  const activeLayer = activeLayers?.all
    ? "all"
    : ["aqi", "ndvi", "water_health", "lst"].find(
        (layerId) => activeLayers?.[layerId],
      );
  const legendConfig = activeLayer
    ? getLayerLegendConfig(activeLayer, {
        aqiSurface,
        ndviSurface,
        waterHealthSurface,
        lstSurface,
        compositeSurface,
      })
    : null;

  return (
    <div
      className="slide-in-up"
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 30,
        padding: "0 20px 36px", // 36px = above 22px status bar
        animationDelay: "0.2s",
      }}
    >
      <SeverityLegend config={legendConfig} marker={markerValue} />
      <CitySelector activeCity={activeCity} onSelect={onSelectCity} />
    </div>
  );
}

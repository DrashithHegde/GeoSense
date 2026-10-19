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
  { value: 0.05, label: "Very low", rgb: [214, 39, 129] },
  { value: 0.1, label: "Low", rgb: [255, 94, 40] },
  { value: 0.2, label: "Moderate", rgb: [255, 205, 50] },
  { value: 0.35, label: "Moderate-high", rgb: [168, 230, 53] },
  { value: 0.55, label: "High", rgb: [41, 217, 103] },
  { value: 0.8, label: "Very high", rgb: [20, 200, 180] },
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
  { position: 0, temperature_c: -1.2, label: "Cool", color: "#2563eb" },
  { position: 0.2, temperature_c: 9.2, label: "Cool", color: "#06b6d4" },
  { position: 0.45, temperature_c: 22.3, label: "Moderate", color: "#facc15" },
  { position: 0.7, temperature_c: 35.4, label: "Hot", color: "#f97316" },
  { position: 0.88, temperature_c: 44.8, label: "Very hot", color: "#ef4444" },
  { position: 1, temperature_c: 51, label: "Very hot", color: "#7f1d1d" },
];

const COMPOSITE_STOPS = [
  { value: 0, color: "#1dd1a1" },
  { value: 25, color: "#ffd32a" },
  { value: 50, color: "#ff8c00" },
  { value: 70, color: "#ff3b3b" },
  { value: 85, color: "#8F3F97" },
  { value: 100, color: "#7E0023" },
];

function rgbToHex(rgb) {
  return `#${rgb.map((channel) => Math.round(channel).toString(16).padStart(2, "0")).join("")}`;
}

function numericLabel(value, digits = 2) {
  return Number(value).toFixed(digits);
}

function getLayerLegendConfig(
  layerId,
  { aqiSurface, ndviSurface, waterHealthSurface, lstSurface },
) {
  if (layerId === "aqi") {
    if (!aqiSurface) return null;
    return {
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

  return {
    stops: COMPOSITE_STOPS.map((stop) => ({
      position: stop.value,
      color: stop.color,
    })),
    minimumLabel: "LOW IMPACT",
    maximumLabel: "CRITICAL",
    minimumColor: COMPOSITE_STOPS[0].color,
    maximumColor: COMPOSITE_STOPS.at(-1).color,
  };
}

function SeverityLegend({ config }) {
  if (!config) return null;
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
      <div
        className="severity-gradient-bar"
        role="img"
        aria-label={`${config.minimumLabel} to ${config.maximumLabel}`}
        style={{
          background: `linear-gradient(to right, ${gradient})`,
          marginBottom: 5,
        }}
      />
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
      <SeverityLegend config={legendConfig} />
      <CitySelector activeCity={activeCity} onSelect={onSelectCity} />
    </div>
  );
}

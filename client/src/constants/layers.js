// -----------------------------------------------------------------------------
// DATA LAYER CONFIGURATION
// -----------------------------------------------------------------------------

export const LAYER_CONFIG = {
  aqi: {
    id: "aqi",
    label: "AQI",
    icon: "○",
    desc: "Air Quality Index (India national scale)",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.1: "#00A859", // Good
      0.2: "#8CC63F", // Satisfactory
      0.4: "#FFF200", // Moderate
      0.6: "#F7931E", // Poor
      0.8: "#ED1C24", // Very Poor
      1.0: "#9E0B0F", // Severe
    },
    blobColors: [
      "rgba(255,59,59,0.28)",
      "rgba(255,140,0,0.20)",
      "rgba(255,211,42,0.14)",
    ],
  },

  ndvi: {
    id: "ndvi",
    label: "NDVI · Vegetation Signal",
    icon: "◇",
    desc: "Satellite normalised difference vegetation index",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.05: "#564234", // bare / built
      0.2: "#b08c4c", // sparse
      0.4: "#dac860", // light vegetation
      0.6: "#96d04c", // moderate
      0.8: "#3cbc54", // dense
      1.0: "#18964e", // very dense
    },
    blobColors: [
      "rgba(41,217,103,0.28)",
      "rgba(168,230,53,0.20)",
      "rgba(255,205,50,0.14)",
    ],
  },

  water_health: {
    id: "water_health",
    label: "Water Health",
    icon: "◈",
    desc: "Water condition index 0..1 (MNDWI water pixels)",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.05: "#052a3a", // dark teal — low
      0.3: "#04527e", // blue
      0.55: "#008ab8", // mid blue
      0.78: "#00c0dc", // cyan
      1.0: "#1ee8ee", // turquoise — high
    },
    blobColors: [
      "rgba(0,192,220,0.25)",
      "rgba(4,82,126,0.20)",
      "rgba(30,232,238,0.12)",
    ],
  },

  lst: {
    id: "lst",
    label: "LST — Land Surface Temperature",
    icon: "▣",
    desc: "Resolution: 30 m · Unit: °C",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.1: "#342696", // coolest
      0.3: "#621ea2",
      0.45: "#982296",
      0.6: "#ce3a70",
      0.75: "#ee6548",
      0.9: "#fa9d34",
      1.0: "#fdde5e", // hottest
    },
    blobColors: [
      "rgba(255,98,48,0.28)",
      "rgba(188,42,108,0.22)",
      "rgba(88,28,118,0.14)",
    ],
  },

  all: {
    id: "all",
    label: "Composite View",
    icon: "⊚",
    desc: "Combined multi-metric overlay",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.1: "#205c78", // low stress
      0.3: "#268c8a",
      0.45: "#6eaa78",
      0.6: "#d6c45c",
      0.75: "#f4903e",
      0.9: "#e2463c",
      1.0: "#b01e60", // critical
    },
    blobColors: [
      "rgba(255,59,59,0.30)",
      "rgba(255,140,0,0.22)",
      "rgba(255,211,42,0.16)",
    ],
  },
};

// -----------------------------------------------------------------------------
// SEVERITY COLORS
// -----------------------------------------------------------------------------

export const SEVERITY_COLORS = {
  critical: {
    ring: "rgba(255,59,59,0.9)",
    glow: "rgba(255,59,59,0.35)",
    fill: "rgba(255,59,59,0.12)",
    hex: "#ff3b3b",
  },
  severe: {
    ring: "rgba(255,140,0,0.9)",
    glow: "rgba(255,140,0,0.3)",
    fill: "rgba(255,140,0,0.1)",
    hex: "#ff8c00",
  },
  high: {
    ring: "rgba(255,211,42,0.9)",
    glow: "rgba(255,211,42,0.25)",
    fill: "rgba(255,211,42,0.08)",
    hex: "#ffd32a",
  },
  moderate: {
    ring: "rgba(29,209,161,0.9)",
    glow: "rgba(29,209,161,0.2)",
    fill: "rgba(29,209,161,0.08)",
    hex: "#1dd1a1",
  },
};
export const MAPBOX_TOKEN = import.meta.env?.VITE_MAPBOX_TOKEN || "";

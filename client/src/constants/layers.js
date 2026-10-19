// -----------------------------------------------------------------------------
// DATA LAYER CONFIGURATION
// -----------------------------------------------------------------------------

export const LAYER_CONFIG = {
  aqi: {
    id: "aqi",
    label: "CPCB AQI",
    icon: "○",
    desc: "National AQI (CPCB)",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.2: "#00E400", // Green
      0.45: "#FFFF00", // Light Green
      0.6: "#FF7E00", // Orange
      0.8: "#FF0000", // Red
      0.9: "#8F3F97", // Purple
      1.0: "#7E0023", // Maroon
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
      0.0: "rgba(0,0,0,0)", // transparent (urban/water/bare)
      0.05: "#d62781", // magenta  — very low
      0.15: "#ff5e28", // orange   — low
      0.3: "#ffcd32", // yellow   — moderate
      0.5: "#a8e635", // lime     — moderate-high
      0.7: "#29d967", // green    — high
      0.9: "#14c8b4", // teal     — very high
      1.0: "#14c8b4",
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
      0.05: "#dd269a", // magenta  — degraded
      0.18: "#ff3b3b", // red
      0.38: "#ff8c00", // orange   — fair
      0.58: "#ffd23c", // yellow   — good
      0.78: "#5cd648", // lime/green very good
      1.0: "#12c8d4", // teal/cyan healthy
    },
    blobColors: [
      "rgba(18,200,212,0.25)",
      "rgba(92,214,72,0.18)",
      "rgba(255,61,61,0.12)",
    ],
  },

  lst: {
    id: "lst",
    label: "LST — Land Surface Temperature",
    icon: "▣",
    desc: "Resolution: 30 m · Unit: °C",
    gradient: {
      0.0: "rgba(0,0,0,0)", // 20C (Black/Transparent)
      0.1: "#12081c", // 23C (Very deep purple)
      0.3: "#581c76", // 29C (Purple)
      0.46: "#bc2a6c", // 34C (Hot magenta)
      0.6: "#ff6230", // 38C (Red-orange)
      0.76: "#ffebc3", // 43C (Near-white)
      1.0: "#ffffff", // 50C (White)
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
      0.2: "#00E400", // Green
      0.45: "#FFFF00", // Light Green
      0.6: "#FF7E00", // Orange
      0.8: "#FF0000", // Red
      0.9: "#8F3F97", // Purple
      1.0: "#7E0023", // Maroon
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

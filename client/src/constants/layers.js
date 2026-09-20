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
    label: "NDVI",
    icon: "◇",
    desc: "Vegetation health index",
    gradient: {
      0.0: "#5C4033", // Dark Brown
      0.2: "#8B4513", // Brown
      0.45: "#D2B48C", // Light Brown
      0.6: "#FFFF00", // Yellow
      0.8: "#32CD32", // Light Green
      0.9: "#008000", // Green
      1.0: "#006400", // Dark Green
    },
    blobColors: [
      "rgba(0,180,216,0.28)",
      "rgba(72,202,228,0.20)",
      "rgba(0,119,182,0.14)",
    ],
  },

  water_health: {
    id: "water_health",
    label: "Water Health",
    icon: "◈",
    desc: "Water condition indicator",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.2: "#1dd1a1",
      0.45: "#ffd32a",
      0.7: "#ff8c00",
      1.0: "#ff3b3b",
    },
    blobColors: [
      "rgba(196,18,31,0.25)",
      "rgba(116,198,157,0.18)",
      "rgba(45,106,79,0.12)",
    ],
  },

  lst: {
    id: "lst",
    label: "LST",
    icon: "▣",
    desc: "Land surface temperature",
    gradient: {
      0.0: "#00008B", // Dark Blue
      0.25: "#00BFFF", // Light Blue
      0.5: "#008000", // Green
      0.6: "#FFFF00", // Yellow
      0.75: "#FF7E00", // Orange
      0.9: "#FF0000", // Red
      1.0: "#8B0000", // Dark Red
    },
    blobColors: [
      "rgba(255,59,59,0.28)",
      "rgba(255,120,0,0.22)",
      "rgba(255,211,42,0.14)",
    ],
  },

  all: {
    id: "all",
    label: "Composite View",
    icon: "⊚",
    desc: "Combined multi-metric overlay",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.15: "rgba(29,209,161,0.6)",
      0.35: "rgba(255,211,42,0.75)",
      0.6: "rgba(255,140,0,0.85)",
      0.85: "rgba(255,59,59,0.95)",
      1.0: "rgba(255,255,255,0.9)",
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

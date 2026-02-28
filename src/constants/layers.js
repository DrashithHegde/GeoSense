// ─────────────────────────────────────────────────────────────────────────────
// DATA LAYER CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

export const LAYER_CONFIG = {
  air: {
    id: "air",
    label: "Air",
    icon: "○",
    desc: "AQI & particulate density",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.15: "rgba(29,209,161,0.6)",
      0.4: "rgba(255,211,42,0.75)",
      0.7: "rgba(255,140,0,0.85)",
      1.0: "rgba(255,59,59,0.95)",
    },
    blobColors: [
      "rgba(255,59,59,0.28)",
      "rgba(255,140,0,0.20)",
      "rgba(255,211,42,0.14)",
    ],
  },

  water: {
    id: "water",
    label: "Water",
    icon: "◈",
    desc: "Contamination risk index",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.2: "rgba(0,119,182,0.55)",
      0.5: "rgba(0,180,216,0.75)",
      0.8: "rgba(72,202,228,0.85)",
      1.0: "rgba(255,59,59,0.9)",
    },
    blobColors: [
      "rgba(0,180,216,0.28)",
      "rgba(72,202,228,0.20)",
      "rgba(0,119,182,0.14)",
    ],
  },

  land: {
    id: "land",
    label: "Land",
    icon: "◇",
    desc: "Degradation & soil stress",
    gradient: {
      0.0: "rgba(0,0,0,0)",
      0.2: "rgba(45,106,79,0.6)",
      0.5: "rgba(116,198,157,0.75)",
      0.8: "rgba(212,160,23,0.85)",
      1.0: "rgba(196,18,31,0.95)",
    },
    blobColors: [
      "rgba(196,18,31,0.25)",
      "rgba(116,198,157,0.18)",
      "rgba(45,106,79,0.12)",
    ],
  },

  all: {
    id: "all",
    label: "All Layers",
    icon: "⬡",
    desc: "Composite anomaly index",
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

// ─────────────────────────────────────────────────────────────────────────────
// SEVERITY COLORS
// ─────────────────────────────────────────────────────────────────────────────

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

// Mapbox token — set VITE_MAPBOX_TOKEN in your .env file
export const MAPBOX_TOKEN = import.meta.env?.VITE_MAPBOX_TOKEN || "";

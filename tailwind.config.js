/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:     "#0b0f14",
        cyan:   "#00e5ff",
        red:    "#ff3b3b",
        orange: "#ff8c00",
        yellow: "#ffd32a",
        green:  "#1dd1a1",
      },
      fontFamily: {
        mono:    ["DM Mono", "monospace"],
        display: ["Syne", "sans-serif"],
      },
      animation: {
        "anomaly-pulse": "anomalyPulse 2s ease-in-out infinite",
        "anomaly-ring":  "anomalyRing 2s ease-out infinite",
        "glob-pulse":    "globePulse 3s ease-in-out infinite",
        "rec-blink":     "recBlink 1.6s ease-in-out infinite",
        "status-pulse":  "statusPulse 2.2s ease-in-out infinite",
        "heat-drift":    "heatDrift 6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

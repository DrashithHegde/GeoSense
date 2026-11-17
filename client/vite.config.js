import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // Mapbox GL is most of the bundle and changes far less often than the app: its own file stays
    // cached in the browser across GeoSense releases
    chunkSizeWarningLimit: 1800,
    rollupOptions: {
      output: {
        manualChunks: { mapbox: ["mapbox-gl"], react: ["react", "react-dom"] },
      },
    },
  },
  server: {
    port: 5173,
    open: false,
    host: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});

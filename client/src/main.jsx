import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "mapbox-gl/dist/mapbox-gl.css";

console.log("🔥🔥🔥 MAIN.JSX LOADED - VERSION 3.0 - TIME:", new Date().toISOString(), "🔥🔥🔥");

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

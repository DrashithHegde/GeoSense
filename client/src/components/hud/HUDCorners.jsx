// ─────────────────────────────────────────────────────────────────────────────
// HUDCorners
// Renders the four surveillance-style corner bracket overlays
// ─────────────────────────────────────────────────────────────────────────────

export default function HUDCorners() {
  return (
    <>
      <div className="hud-corner hud-tl" />
      <div className="hud-corner hud-tr" />
      <div className="hud-corner hud-bl" />
      <div className="hud-corner hud-br" />
    </>
  );
}

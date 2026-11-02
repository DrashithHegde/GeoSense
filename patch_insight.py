import re
from pathlib import Path

path = Path("client/src/components/panels/InsightPanel.jsx")
content = path.read_text(encoding="utf-8")

old_body = """            {/* ── Body ───────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: isCompositeView ? "auto" : "visible", padding: "16px 18px" }}>

              {/* Active score */}
              <div"""

new_body = """            {/* ── Body ───────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: isCompositeView ? "auto" : "visible", padding: "16px 18px" }}>

              {activeLayerId === "lst" && zone?.pixelLST && !zone.pixelLST.nodata && (
                <div
                  style={{
                    marginBottom: 16,
                    padding: 12,
                    background: "rgba(255, 95, 87, 0.08)",
                    borderLeft: "3px solid #ff5f57",
                    borderRadius: 4,
                  }}
                >
                  <div style={{ fontSize: "0.58rem", color: "var(--text-dim)", letterSpacing: "0.18em", textTransform: "uppercase" }}>
                    Pixel Measurement
                  </div>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 4 }}>
                    <span style={{ fontFamily: "'DM Mono', monospace", fontSize: "1.8rem", fontWeight: 600, color: "#ff5f57" }}>
                      {zone.pixelLST.value_c.toFixed(1)}
                    </span>
                    <span style={{ fontSize: "1rem", color: "#ff5f57", opacity: 0.8 }}>°C</span>
                  </div>
                  <div style={{ fontSize: "0.6rem", color: "var(--text-dim)", marginTop: 4 }}>
                    Source: {zone.pixelLST.source}
                  </div>
                </div>
              )}

              {/* Active score */}
              <div"""

content = content.replace(old_body, new_body)

old_panelLabel = """  const panelLabel = isCompositeView
    ? "Composite Risk Score"
    : `${activeLayerMeta.label} Metric`;"""

new_panelLabel = """  const panelLabel = isCompositeView
    ? "Composite Risk Score"
    : activeLayerId === "lst" && zone?.pixelLST && !zone.pixelLST.nodata
    ? "Analytical Zone Mean LST"
    : `${activeLayerMeta.label} Metric`;"""
    
content = content.replace(old_panelLabel, new_panelLabel)

path.write_text(content, encoding="utf-8")
print("Patched InsightPanel.jsx")

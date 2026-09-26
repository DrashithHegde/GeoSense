import re
from pathlib import Path

path = Path("client/src/constants/layers.js")
content = path.read_text(encoding="utf-8")

old_lst = """  lst: {
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
  },"""

new_lst = """  lst: {
    id: "lst",
    label: "LST",
    icon: "▣",
    desc: "Land surface temperature",
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
  },"""

content = content.replace(old_lst, new_lst)
path.write_text(content, encoding="utf-8")
print("Patched layers.js")

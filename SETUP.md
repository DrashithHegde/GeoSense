# GeoSense — run it on Windows in VS Code

## What you need (install once)
- **Python 3.12** — python.org (tick *Add python.exe to PATH*)
- **Node.js 20+** — nodejs.org
- **Docker Desktop** — runs the PostGIS database (or use your own PostgreSQL + PostGIS and add `-NoDocker`)
- **VS Code** — open this folder; accept *Install recommended extensions*

## 1. Open in VS Code
`File → Open Folder… →` this `GeoSense` folder.

## 2. First-time setup (one command)
In the VS Code terminal (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
- First run creates `.env` and opens it in Notepad. Fill in:
  - `DB_PASSWORD` / `POSTGRES_PASSWORD` (same value)
  - `OPENAQ_AQI_KEY` — free at https://explore.openaq.org/register (for live CPCB AQI)
  - `VITE_MAPBOX_TOKEN` — free at https://account.mapbox.com/
  - optional: `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` for AI-written explanations
- Run the same command again. It will: start PostGIS → create `server\.venv` → install packages →
  run migrations → build the 300 m grid → install frontend packages → render heatmaps →
  fetch AQI → build composite → run the ML (Isolation Forest + XGBoost + Water Health) → run tests.

(Or in VS Code: `Terminal → Run Task… → Setup: first-time (everything)`.)

## 3. Run
```powershell
.\run.ps1
```
Opens the backend (http://localhost:8000/docs) and frontend (http://localhost:5173).

In VS Code you can instead:
- `Terminal → Run Task… → GeoSense: start all`, or
- `Run and Debug (Ctrl+Shift+D) → GeoSense: full stack` (breakpoints work in the Python backend)

Then: pick **Mumbai** → click anywhere on the map → **Deep Analysis**.

## 4. Refresh data later
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PipelineOnly
```
Re-renders heatmaps, re-fetches AQI and re-runs the ML.

## Troubleshooting
| Problem | Fix |
|---|---|
| `alembic failed` | Docker Desktop not running, or DB_* in `.env` wrong |
| AQI shows “unavailable” | Fewer than 3 CPCB/MPCB stations reported in the last 48 h — expected; try later |
| No AI write-up | No LLM key in `.env` — evidence-only explanation is shown instead |
| Map is blank | `VITE_MAPBOX_TOKEN` missing in `.env` → re-run setup (it writes `client\.env`) |
| `pip` fails building numpy | You're on Python 3.13/3.14 — install 3.12 and delete `server\.venv` |

## About `geosense-intelligence.bundle`
A git bundle is a single file containing git commits — like an offline `git push`. You only
need it if you want this work as a branch inside your existing git clone:
`git fetch path\to\geosense-intelligence.bundle feature/intelligence-layer:feature/intelligence-layer`.
If you use this zip, you can ignore the bundle.

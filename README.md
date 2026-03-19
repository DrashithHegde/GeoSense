# GeoSense

GeoSense is a full-stack environmental intelligence project with:
- **Client**: React + Vite geospatial dashboard
- **Server**: FastAPI backend scaffold

## Repository Structure

- `client/` — frontend app (map UI, panels, interactions)
- `server/` — backend API scaffold

## Quick Start

### 1) Frontend

```bash
cd client
npm install
copy .env.example .env
npm run dev
```

### 2) Backend

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

## Environment Variables

- Frontend expects `VITE_MAPBOX_TOKEN` in `client/.env`
- Backend config template is in `server/.env.example`

## Docs

- Backend details: `server/README.md`

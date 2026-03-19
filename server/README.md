# GeoSense Server (FastAPI)

Minimal backend scaffold for easy frontend integration.

## Structure

- `app/main.py` → FastAPI app + CORS + `/api` router mount
- `app/api/routes.py` → starter endpoints
- `app/core/config.py` → env-based settings
- `app/schemas/anomaly.py` → response models
- `run.py` → local entrypoint with auto-reload in development

## Quick start

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

API will run at `http://127.0.0.1:8000`.

## Starter endpoints

- `GET /api/health`
- `GET /api/anomalies?city=mumbai`

## Frontend integration

`client/vite.config.js` already proxies `/api` to `http://127.0.0.1:8000`.
So from React, call:

```js
fetch('/api/health')
```

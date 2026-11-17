# Deploying GeoSense

Two independent deployments of the same code:

| | Primary (long-term) | Secondary (while Azure credits last) |
|---|---|---|
| Frontend | **Vercel** (`client/`) | **Azure Static Web Apps** (`client/`) |
| API | **Render** web service (Docker, `server/Dockerfile`) | **Azure App Service** for containers (image from GitHub Container Registry) |
| Database | **Render Postgres 16** + PostGIS + pgvector | **Azure Database for PostgreSQL flexible server** + PostGIS + pgvector |
| Map layers | data bundle on a **GitHub Release** | data bundle in **Azure Blob Storage** |

**Fallback when the Azure credits run out.** Both frontends list both APIs in `VITE_API_URLS`,
Azure first. The browser uses the first API that answers; when the Azure app is stopped it gets a
platform error page or no answer, and the next API (Render) is used for the rest of the session.
Both APIs list both bundle URLs in `DATA_BUNDLE_URL` (Blob first, GitHub Release second), so the
Render API keeps starting after the Blob container is gone. Nothing has to be redeployed when Azure
stops; the Vercel site and the Render API keep working on their own.

The heavy work (Earth Engine, OpenAQ history, ML training) never runs on the servers. You run it on
your machine, then publish two things: the **database** (a `pg_dump`) and the **data bundle** (map
layers + ML summaries).

---

## 0. Prepare everything locally

From `server/`, with Postgres running (`docker compose up -d db`):

```bash
# every city's layers, cells, models (Earth Engine + OPENAQ_AQI_KEY needed)
python scripts/setup_city.py --city mumbai --from render     # Mumbai's rasters already exist
python scripts/setup_city.py --city delhi
python scripts/setup_city.py --city bengaluru
python scripts/ingest_corpus.py --embed-only                  # RAG vectors for the new notes

# the data bundle for the servers
python scripts/data_bundle.py pack --out geosense-data.tar.gz

# the database: data only (the servers create the schema themselves) ...
docker compose exec -T db pg_dump -U postgres -d geosense -Fc --data-only --no-owner --no-acl \
  --exclude-table=alembic_version --exclude-table=spatial_ref_sys \
  --exclude-table=rag_items --exclude-table=rag_meta > geosense-data.dump
# ... plus the RAG vector tables with their schema (made by the ingestion, not by migrations)
docker compose exec -T db pg_dump -U postgres -d geosense -Fc --no-owner --no-acl \
  -t rag_items -t rag_meta > geosense-rag.dump
```

(On Windows PowerShell use `cmd /c "docker compose exec -T db pg_dump ... > file"` so the binary
dump is not re-encoded.) The document passages behind the RAG citations are read from `rag_items`
on the servers; the third-party documents themselves are never uploaded.

Publish `geosense-data.tar.gz`:
* **GitHub Release**: repository → Releases → new release (e.g. tag `data-2026-11`) → attach the
  file. URL: `https://github.com/<owner>/<repo>/releases/download/data-2026-11/geosense-data.tar.gz`
  (the repository must be public for the server to download it without a token).
* **Azure Blob** (section 3).

---

## 1. Render (API + database)

1. Render dashboard → **New → Blueprint** → this repository. `render.yaml` creates
   `geosense-api` (Docker, Singapore) and `geosense-db` (PostgreSQL 16).
2. Fill the prompted values:
   * `CORS_ORIGINS` = your Vercel URL (and the Azure Static Web App URL), comma-separated
   * `DATA_BUNDLE_URL` = `<Blob SAS URL>,<GitHub Release URL>` (or just the GitHub one)
   * `OPENAQ_AQI_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `MAPBOX_TOKEN`
3. First start: `deploy/start.sh` downloads the bundle, runs `scripts/db_init.py` (creates the
   `postgis` and `vector` extensions — both supported by Render Postgres — and runs every
   migration), then starts the API. `/api/health` must show `"database": "ok"`.
4. Load the data into the database (Render → geosense-db → **Connect → External** URL):
   ```bash
   pg_restore --no-owner --no-acl -d "<external database URL>" geosense-rag.dump
   pg_restore --data-only --no-owner --no-acl -d "<external database URL>" geosense-data.dump
   ```
   then restart the API once (it reads the RAG passages at start-up).
5. Check: `https://<api>.onrender.com/api/cities` lists the three cities with their layers.

Plans: the API needs ~320 MB with keyword retrieval (`RAG_EMBEDDER=off`, fits the 512 MB plan) and
~500 MB with sentence embeddings (`RAG_EMBEDDER=auto`, use the `1c-2g` plan). The free web plan
works for a demo but sleeps after 15 idle minutes (the site waits up to 2 minutes for it to wake),
and a free database is deleted after 30 days.

## 2. Vercel (frontend)

1. Vercel → **Add New → Project** → this repository → **Root Directory: `client`** (Vite is
   detected; `client/vercel.json` sets the build and the single-page rewrites).
2. Environment variables (Production and Preview):
   * `VITE_API_URLS` = `https://<azure-api>.azurewebsites.net,https://<api>.onrender.com`
     (only the Render URL if you are not using Azure)
   * `VITE_MAPBOX_TOKEN` = your public `pk.` token; in the Mapbox account restrict it to the Vercel
     and Static Web App URLs.
3. Deploy, then put the Vercel URL into `CORS_ORIGINS` on both APIs.

## 3. Azure (secondary)

Variables used below (choose your own names):

```bash
RG=geosense-rg; LOC=centralindia; PG=geosense-pg; SA=geosensedata$RANDOM; PLAN=geosense-plan; APP=geosense-api
az group create -n $RG -l $LOC
```

**Database** — PostgreSQL 16 flexible server, extensions allow-listed:

```bash
az postgres flexible-server create -g $RG -n $PG -l $LOC --tier Burstable --sku-name Standard_B1ms \
  --version 16 --storage-size 32 --admin-user geosense --admin-password '<strong password>' \
  --public-access 0.0.0.0          # allows Azure services; add your own IP to load the dump
az postgres flexible-server db create -g $RG -s $PG -d geosense
az postgres flexible-server parameter set -g $RG -s $PG --name azure.extensions --value POSTGIS,VECTOR
```

Connection string for the app (SSL is required on Azure):
`postgresql://geosense:<password>@$PG.postgres.database.azure.com:5432/geosense?sslmode=require`

**Blob storage** — the data bundle:

```bash
az storage account create -g $RG -n $SA -l $LOC --sku Standard_LRS
az storage container create --account-name $SA -n geosense
az storage blob upload --account-name $SA -c geosense -n geosense-data.tar.gz -f geosense-data.tar.gz
az storage blob generate-sas --account-name $SA -c geosense -n geosense-data.tar.gz \
  --permissions r --expiry 2027-12-31 --full-uri -o tsv          # -> the Blob URL for DATA_BUNDLE_URL
```

**API** — App Service for containers running the image built by `.github/workflows/api-image.yml`
(`ghcr.io/<owner>/geosense-api:latest`; make the package public on GitHub, or add registry
credentials to the web app):

```bash
az appservice plan create -g $RG -n $PLAN --is-linux --sku B1          # 1.75 GB: hybrid RAG fits
az webapp create -g $RG -p $PLAN -n $APP -i ghcr.io/<owner>/geosense-api:latest
az webapp config appsettings set -g $RG -n $APP --settings \
  WEBSITES_PORT=8000 \
  DATABASE_URL='postgresql://geosense:<password>@'$PG'.postgres.database.azure.com:5432/geosense?sslmode=require' \
  DATA_BUNDLE_URL='<Blob SAS URL>,<GitHub Release URL>' \
  CORS_ORIGINS='https://<site>.vercel.app,https://<static-web-app>.azurestaticapps.net' \
  OPENAQ_AQI_KEY='...' GEMINI_API_KEY='...' GROQ_API_KEY='...' MAPBOX_TOKEN='...' \
  ADMIN_TOKEN='<random>' RAG_EMBEDDER=auto AI_MODE=summary
az webapp config set -g $RG -n $APP --always-on true
```

Load the database exactly as for Render (both `pg_restore` commands, with the Azure connection
string) after the app has started once (it creates the extensions and the schema), then restart it.

**Frontend** — Static Web Apps (Free plan): Azure portal → Static Web App → GitHub → this
repository, *app location* `client`, *output location* `dist`, build preset *Vite*. Add the same
`VITE_API_URLS` and `VITE_MAPBOX_TOKEN` as on Vercel (as build-time environment variables in the
generated GitHub workflow). `client/public/staticwebapp.config.json` handles the page routing.

## 4. Keeping the AQI layer current

Each API rebuilds every city's AQI layer from OpenAQ every few hours by itself
(`AQI_AUTO_REFRESH`, needs `OPENAQ_AQI_KEY`) and rebuilds the composite with it. After a restart the
layer from the bundle is older than 6 h, so the first refresh starts ~20 s after start-up; until
then (or if OpenAQ is down) the bundled layer is shown until its readings pass 48 h, then hidden.

## 5. Updating data later

Re-run the city pipeline locally, then `data_bundle.py pack` and upload the new bundle **under a
new file name or release tag**, and update `DATA_BUNDLE_URL` (the API downloads the bundle when it
starts). For the database, make a new data-only dump, empty the hosted tables, and restore:

```bash
psql "<hosted database URL>" -c "TRUNCATE spatial_cells, environment_data, engineered_features, anomaly_results, history_seasons, cell_history, station_aqi_history, zones RESTART IDENTITY CASCADE"
pg_restore --data-only --no-owner --no-acl -d "<hosted database URL>" geosense-data.dump
```

If you re-ingested the RAG corpus, also run `DROP TABLE rag_items, rag_meta` on the hosted database
and restore `geosense-rag.dump` again.

## 6. Checklist

* `https://<api>/api/health` → `database: ok`
* `https://<api>/api/cities` → three cities, layers `generated`
* the site loads, each city flies in with its layers, a click shows the 300 m area panel
* `CORS_ORIGINS` contains every site URL; Mapbox token restricted to them
* secrets only in the platforms' settings, never in the repository

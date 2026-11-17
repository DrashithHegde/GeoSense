#!/bin/sh
# GeoSense API container start (Render, Azure App Service, docker run).
#  1. fetch the data bundle (map layers, ML summaries) when DATA_BUNDLE_URL is set
#     (comma-separated URLs are tried in order, e.g. Azure Blob first, GitHub Release second)
#  2. prepare the database: PostGIS + pgvector extensions, migrations (MIGRATE_ON_START=0 skips)
#  3. start the API on $PORT (Render sets it; Azure: WEBSITES_PORT=8000)
set -e
cd /app
if [ -n "$DATA_BUNDLE_URL" ]; then
  python scripts/data_bundle.py fetch || echo "WARNING: data bundle not fetched - layers without files will be reported as unavailable"
fi
if [ "${MIGRATE_ON_START:-1}" != "0" ]; then
  python scripts/db_init.py || echo "WARNING: database not prepared (is DATABASE_URL set and reachable?)"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips="*" --timeout-keep-alive 30

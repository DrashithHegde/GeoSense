#!/bin/sh
# GeoSense API container start (Render, Azure App Service, docker run).
#  1. fetch the data bundle (map layers, ML summaries) when DATA_BUNDLE_URL is set
#  2. prepare the database and run migrations
#  3. start the API on $PORT
set -e
cd /app
PORT_VALUE="${PORT:-8000}"
echo "GeoSense API startup: port=$PORT_VALUE migrate=${MIGRATE_ON_START:-1} warm_up=${WARM_UP:-1}"
echo "GeoSense API startup: database_configured=$([ -n "${DATABASE_URL:-}" ] && echo yes || echo no)"
if [ -n "$DATA_BUNDLE_URL" ]; then
  python scripts/data_bundle.py fetch || echo "WARNING: data bundle not fetched - layers without files will be reported as unavailable"
fi
if [ "${MIGRATE_ON_START:-1}" != "0" ]; then
  python scripts/db_init.py || echo "WARNING: database not prepared (is DATABASE_URL set and reachable?)"
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT_VALUE" --workers 1 --proxy-headers --forwarded-allow-ips="*" --timeout-keep-alive 30 --log-level info

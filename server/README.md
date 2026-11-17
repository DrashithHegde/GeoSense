# GeoSense API (FastAPI)

See the main [README](../README.md) for what it does and how to run it, and
[deploy/DEPLOY.md](../deploy/DEPLOY.md) for hosting.

```bash
pip install -r requirements-pipeline.txt   # requirements.txt = what the deployed API needs
python scripts/db_init.py                  # PostGIS + pgvector + migrations
uvicorn app.main:app --reload --port 8000  # http://127.0.0.1:8000/docs
python -m pytest tests -q
```

Pipeline scripts (all take `--city mumbai|delhi|bengaluru`): `scripts/setup_city.py` runs them in
order; `scripts/data_bundle.py` packs / fetches the layers for a server.

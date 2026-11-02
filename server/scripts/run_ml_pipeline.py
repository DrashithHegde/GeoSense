"""GeoSense cell ML pipeline (real rasters -> 300 m cells -> IF + XGBoost + WH z).

    python scripts/run_ml_pipeline.py

Steps:
  1. zonal statistics from NDVI / Water Health / LST (/ AQI if generated) GeoTIFFs
  2. upsert environment_data + engineered_features (cell_id, snapshot)
  3. Isolation Forest, XGBoost LST residual model, Water Health robust z
  4. upsert anomaly_results per model, write data/ml/ml_summary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.database import get_db  # noqa: E402
from app.services.ml.pipeline import run_cell_ml_pipeline  # noqa: E402


def main() -> int:
    t = time.time()
    with get_db() as db:
        summary = run_cell_ml_pipeline(db)
    print(json.dumps(summary, indent=2, default=float))
    print(f"done in {time.time() - t:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

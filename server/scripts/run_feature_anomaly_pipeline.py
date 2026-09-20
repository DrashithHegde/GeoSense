"""Run the Phase 2 feature engineering and Isolation Forest pipeline.

Usage:
    python scripts/run_feature_anomaly_pipeline.py
    python scripts/run_feature_anomaly_pipeline.py --date 2026-08-16
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys

# Allow direct execution from the server directory, matching the ingestion scripts.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.feature_anomaly_pipeline import run_feature_anomaly_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GeoSense features and spatial anomalies from stored real data")
    parser.add_argument("--date", type=date.fromisoformat, help="UTC snapshot date (YYYY-MM-DD); defaults to latest modelable date")
    args = parser.parse_args()
    report = run_feature_anomaly_pipeline(args.date)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

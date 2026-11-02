"""Phase 6: API Verification Script using FastAPI TestClient.

Tests:
1. GET /api/health -> healthy, phase, version
2. GET /api/system/status -> returns DB and pipeline status correctly
3. GET /api/anomalies -> returns 18 anomalies matching database
4. GET /api/metrics/latest -> returns 189 zone metrics
5. GET /api/aqi/stations -> returns AQI stations per zone
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient
from app.main import app


def verify_api():
    client = TestClient(app)

    print("=== 1. /api/health ===")
    res = client.get("/api/health")
    print(f"Status Code: {res.status_code}")
    print(f"Response: {res.json()}")
    assert res.status_code == 200
    assert res.json().get("status") == "healthy"

    print("\n=== 2. /api/system/status ===")
    res = client.get("/api/system/status")
    print(f"Status Code: {res.status_code}")
    data = res.json()
    print(f"Raw rows: {data.get('raw_data', {}).get('total_environment_data_rows')}")
    print(f"Duplicates: {data.get('raw_data', {}).get('duplicate_zone_timestamp_rows')}")
    print(f"Latest AQI: {data.get('aqi_latest_snapshot')}")
    print(f"Temporal Readiness: {data.get('temporal_readiness', {}).get('per_metric')}")
    print(f"Spatial Isolation Forest Readiness: {data.get('pipeline_readiness', {}).get('spatial_isolation_forest')}")
    assert res.status_code == 200
    assert data.get("raw_data", {}).get("duplicate_zone_timestamp_rows") == 0

    print("\n=== 3. /api/anomalies ===")
    res = client.get("/api/anomalies?days=30&limit=100")
    print(f"Status Code: {res.status_code}")
    anomalies = res.json()
    print(f"Anomalies returned: {len(anomalies)}")
    if anomalies:
        sample = anomalies[0]
        print(f"Sample anomaly: ID={sample.get('id')}, Locality={sample.get('locality_name')}, Score={sample.get('anomaly_score')}")
        rc = sample.get('root_cause') or ''
        print(f"Root cause: {rc.encode('ascii', 'backslashreplace').decode('ascii')}")
    assert res.status_code == 200
    assert len(anomalies) == 18

    print("\n=== 4. /api/metrics/latest ===")
    res = client.get("/api/metrics/latest")
    print(f"Status Code: {res.status_code}")
    metrics = res.json()
    print(f"Metrics zones returned: {len(metrics)}")
    assert res.status_code == 200
    assert len(metrics) == 189

    print("\n=== 5. /api/aqi/stations ===")
    res = client.get("/api/aqi/stations")
    print(f"Status Code: {res.status_code}")
    stations = res.json()
    print(f"AQI zones with data returned: {len(stations)}")
    assert res.status_code == 200

    print("\nALL API ENDPOINTS VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    verify_api()

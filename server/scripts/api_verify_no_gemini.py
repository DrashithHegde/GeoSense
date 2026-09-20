from fastapi.testclient import TestClient
from app.main import app
from app.database import engine, get_db
from sqlalchemy import text
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = TestClient(app)

def verify():
    # Find an anomaly zone
    with engine.connect() as conn:
        result = conn.execute(text("SELECT zone_id FROM anomaly_results WHERE is_anomaly = true LIMIT 1;")).mappings().first()
        if not result:
            logger.error("No anomaly zone found in database")
            return
        anomaly_zone_id = result["zone_id"]

        result = conn.execute(text("SELECT zone_id FROM anomaly_results WHERE is_anomaly = false LIMIT 1;")).mappings().first()
        inlier_zone_id = result["zone_id"] if result else None

    logger.info(f"=== TESTING ANOMALY ZONE: {anomaly_zone_id} ===")
    response = client.get(f"/api/zones/{anomaly_zone_id}/explanation")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    
    # Assertions
    assert "deterministic_explanation" in data, "deterministic_explanation missing"
    assert "generation_status" in data, "generation_status missing"
    assert data["generation_status"] == "llm_not_configured", f"Expected llm_not_configured, got {data['generation_status']}"
    assert "llm_explanation" not in data, "LLM explanation should not be present"
    assert data["zone_id"] == anomaly_zone_id
    assert data["city"] == "Mumbai"
    assert data["classification"] == "anomaly"
    
    knowledge_ids = [k["knowledge_id"] for k in data["knowledge_context"]]
    assert "mumbai_monsoon_context" in knowledge_ids, "City-specific knowledge not included"
    
    logger.info("Anomaly Zone Verified. Output:")
    logger.info(json.dumps(data, indent=2)[:500] + "\n... truncated ...")

    if inlier_zone_id:
        logger.info(f"\n=== TESTING INLIER ZONE: {inlier_zone_id} ===")
        response = client.get(f"/api/zones/{inlier_zone_id}/explanation")
        assert response.status_code == 200
        data = response.json()
        assert data["classification"] == "inlier"
        assert "llm_explanation" not in data
        assert data["generation_status"] == "llm_not_configured"
        logger.info("Inlier Zone Verified.")

    logger.info("\n=== TESTING UNKNOWN ZONE: 99999 ===")
    response = client.get(f"/api/zones/99999/explanation")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    logger.info("Unknown Zone Verified (404).")

if __name__ == "__main__":
    verify()

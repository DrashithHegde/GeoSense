import json
from app.services.rag_knowledge import get_knowledge_context

def test_cities():
    evidence = {
        "measurements": {"aqi": 100, "lst": 30.0, "ndvi": 0.5, "ndwi": 0.1},
        "isolation_forest": {"is_anomaly": True}
    }
    
    print("=== MUMBAI ===")
    ctx_mumbai = get_knowledge_context(evidence, city="Mumbai")
    ids = [c["knowledge_id"] for c in ctx_mumbai]
    print(f"Retrieved: {ids}")
    assert "mumbai_monsoon_context" in ids, "Mumbai missing its context"
    assert "aqi_cpcb_scale" in ids, "Mumbai missing global context"
    
    print("\n=== BENGALURU ===")
    ctx_blr = get_knowledge_context(evidence, city="Bengaluru")
    ids_blr = [c["knowledge_id"] for c in ctx_blr]
    print(f"Retrieved: {ids_blr}")
    assert "mumbai_monsoon_context" not in ids_blr, "Bengaluru should not have Mumbai context"
    assert "aqi_cpcb_scale" in ids_blr, "Bengaluru missing global context"
    
    print("\n=== NEW DELHI ===")
    ctx_delhi = get_knowledge_context(evidence, city="New Delhi")
    ids_delhi = [c["knowledge_id"] for c in ctx_delhi]
    print(f"Retrieved: {ids_delhi}")
    assert "mumbai_monsoon_context" not in ids_delhi, "New Delhi should not have Mumbai context"
    assert "aqi_cpcb_scale" in ids_delhi, "New Delhi missing global context"
    
    print("\nMulti-city knowledge retrieval verified.")

if __name__ == "__main__":
    test_cities()

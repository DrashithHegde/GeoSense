from fastapi import APIRouter

from app.schemas.anomaly import AnomalyListResponse, AnomalyZone

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geosense-api"}


@router.get("/anomalies", response_model=AnomalyListResponse)
def list_anomalies(city: str = "mumbai") -> AnomalyListResponse:
    seed = [
        AnomalyZone(zone_id="MUM-001", name="Dharavi Industrial Belt", severity=0.84, city="mumbai"),
        AnomalyZone(zone_id="MUM-002", name="Eastern Creek Corridor", severity=0.71, city="mumbai"),
        AnomalyZone(zone_id="MUM-003", name="Aarey Buffer Region", severity=0.58, city="mumbai"),
    ]
    filtered = [item for item in seed if item.city == city.lower()]
    return AnomalyListResponse(city=city.lower(), count=len(filtered), items=filtered)

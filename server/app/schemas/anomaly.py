from pydantic import BaseModel, Field


class AnomalyZone(BaseModel):
    zone_id: str = Field(..., description="Stable identifier for the zone")
    name: str
    severity: float = Field(..., ge=0, le=1)
    city: str


class AnomalyListResponse(BaseModel):
    city: str
    count: int
    items: list[AnomalyZone]

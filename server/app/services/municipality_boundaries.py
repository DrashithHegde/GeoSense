"""Validated, local municipality context geometry for GeoSense.

These geometries are presentation/context assets. They do not alter the frozen
analytical zones or assign one environmental value to an entire municipality.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape


class MunicipalityBoundaryError(RuntimeError):
    """Raised when a required local municipality boundary cannot be trusted."""


BOUNDARY_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "boundaries"
MUNICIPALITIES = (
    ("mumbai", "Mumbai"),
    ("thane", "Thane"),
    ("mira_bhayandar", "Mira-Bhayandar"),
)


def _feature_from_geojson(payload: dict[str, Any], *, municipality_id: str, path: Path) -> dict[str, Any]:
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features") or []
        if len(features) != 1:
            raise MunicipalityBoundaryError(f"{path.name}: expected exactly one GeoJSON feature")
        feature = features[0]
    elif payload.get("type") == "Feature":
        feature = payload
    else:
        raise MunicipalityBoundaryError(f"{path.name}: expected a Feature or FeatureCollection")

    properties = feature.get("properties") or {}
    if properties.get("id") != municipality_id:
        raise MunicipalityBoundaryError(
            f"{path.name}: expected properties.id '{municipality_id}', got {properties.get('id')!r}"
        )
    geometry = feature.get("geometry")
    if not geometry:
        raise MunicipalityBoundaryError(f"{path.name}: geometry is missing")
    try:
        geom = shape(geometry)
    except Exception as exc:
        raise MunicipalityBoundaryError(f"{path.name}: invalid GeoJSON geometry: {exc}") from exc
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise MunicipalityBoundaryError(f"{path.name}: expected Polygon or MultiPolygon, got {geom.geom_type}")
    if geom.is_empty or not geom.is_valid:
        raise MunicipalityBoundaryError(f"{path.name}: invalid geometry")
    return {"id": municipality_id, "name": properties.get("name") or municipality_id, "shapely_geom": geom, "geojson": mapping(geom)}


@lru_cache(maxsize=1)
def load_municipality_boundaries() -> tuple[dict[str, Any], ...]:
    """Load all required WGS84 local assets once; never fall back to network."""
    boundaries: list[dict[str, Any]] = []
    for municipality_id, _display_name in MUNICIPALITIES:
        path = BOUNDARY_DIRECTORY / f"{municipality_id}.geojson"
        if not path.is_file():
            raise MunicipalityBoundaryError(f"Required boundary asset is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MunicipalityBoundaryError(f"Unable to read boundary asset {path}: {exc}") from exc
        boundaries.append(_feature_from_geojson(payload, municipality_id=municipality_id, path=path))
    return tuple(boundaries)

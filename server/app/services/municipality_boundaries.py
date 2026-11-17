"""Validated, local municipality boundaries for each GeoSense city.

The boundary files are read from the city's own folder (see app/core/cities.py) and never
fetched from the network while serving. They define the study region (the union of a city's
municipalities) used to clip rasters and to build the 300 m grid; they never assign one
environmental value to a whole municipality.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

from app.core.cities import get_city


class MunicipalityBoundaryError(RuntimeError):
    """Raised when a required local municipality boundary cannot be trusted."""


def boundary_directory(city_id: str | None = None) -> Path:
    return get_city(city_id).data_dir / "boundaries"


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
    return {"id": municipality_id, "name": properties.get("name") or municipality_id, "shapely_geom": geom,
            "geojson": mapping(geom), "source": properties.get("source")}


@lru_cache(maxsize=8)
def _boundaries(city_id: str) -> tuple[dict[str, Any], ...]:
    city = get_city(city_id)
    out: list[dict[str, Any]] = []
    for municipality_id, display_name in city.municipalities:
        path = boundary_directory(city_id) / f"{municipality_id}.geojson"
        if not path.is_file():
            raise MunicipalityBoundaryError(f"Required boundary asset is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MunicipalityBoundaryError(f"Unable to read boundary asset {path}: {exc}") from exc
        b = _feature_from_geojson(payload, municipality_id=municipality_id, path=path)
        b["name"] = display_name
        out.append(b)
    return tuple(out)


@lru_cache(maxsize=8)
def _region(city_id: str):
    """Union of the city's municipalities with interior holes filled (e.g. Sanjay Gandhi National
    Park inside Mumbai's union, or slivers between dissolved wards)."""
    geometry = unary_union([b["shapely_geom"] for b in _boundaries(city_id)])
    if geometry.geom_type == "Polygon":
        geometry = Polygon(geometry.exterior)
    elif geometry.geom_type == "MultiPolygon":
        geometry = MultiPolygon([Polygon(p.exterior) for p in geometry.geoms])
    if geometry.is_empty or not geometry.is_valid:
        raise MunicipalityBoundaryError(f"The study-region union for {city_id} is invalid")
    return geometry


def load_municipality_boundaries(city_id: str | None = None) -> tuple[dict[str, Any], ...]:
    """The current city's municipalities (local files only; never the network)."""
    return _boundaries(get_city(city_id).id)


def load_study_region_geometry(city_id: str | None = None):
    """The current city's study region (WGS84)."""
    return _region(get_city(city_id).id)


def city_region_or_none(city_id: str):
    try:
        return _region(city_id)
    except MunicipalityBoundaryError:
        return None


def get_study_region_bounds(city_id: str | None = None) -> tuple[float, float, float, float]:
    """West, south, east, north of the current city's study region."""
    west, south, east, north = load_study_region_geometry(city_id).bounds
    if west >= east or south >= north:
        raise MunicipalityBoundaryError("The study-region bounds are invalid")
    return float(west), float(south), float(east), float(north)


def clear_cache() -> None:
    _boundaries.cache_clear()
    _region.cache_clear()

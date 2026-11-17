"""The cities GeoSense covers, and which one a request or script is working on.

Every city has the same pipeline and the same folder layout:

    <data_dir>/boundaries/<municipality>.geojson   study-region boundaries
    <data_dir>/surfaces/manifest.json + rasters      NDVI, LST, Water Health, AQI, composite
    <data_dir>/ml/                                   cell features, models, ml_summary.json
    <data_dir>/history/                              seasonal history summaries

Mumbai keeps the original layout directly under server/data/; every other city lives in
server/data/cities/<id>/. GEOSENSE_DATA_DIR moves the whole data folder (deployments).

The city in use is a context variable: the API sets it per request (?city=..., or the city that
contains ?lon=&lat=), scripts set it with --city, background jobs with `use_city(...)`.
Code that reads or writes city data uses `city_path(...)`, which resolves against the city in
use at the moment it is used, so one module works for every city.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

SERVER_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("GEOSENSE_DATA_DIR") or (SERVER_ROOT / "data")).resolve()


@dataclass(frozen=True)
class City:
    id: str
    name: str                                   # short name used in the UI
    region_label: str                           # what the study region covers, for text and prompts
    municipalities: tuple[tuple[str, str], ...]  # (boundary file id, display name)
    center: tuple[float, float]                 # lon, lat
    zoom: float
    openaq_bbox: tuple[float, float, float, float]   # west, south, east, north (stations near the edge count)
    lst_qc_min_c: float                         # Landsat LST below this = residual cloud (see qc.py)
    seasons: dict[str, tuple[tuple[int, int], tuple[int, int], str]]   # kind -> (start m,d), (end m,d), label
    knowledge_places: tuple[str, ...]           # "city" values of knowledge notes that belong to this city
    kb: dict[str, str] = field(default_factory=dict)   # role -> knowledge note id for city-specific context
    sources: tuple[str, ...] = ()               # where the boundaries come from (shown in provenance)
    subdir: str | None = None                   # None = data directly under DATA_ROOT (Mumbai)

    @property
    def data_dir(self) -> Path:
        return DATA_ROOT if self.subdir is None else DATA_ROOT / "cities" / self.subdir

    @property
    def lat(self) -> float:
        return self.center[1]

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "region_label": self.region_label,
                "center": list(self.center), "zoom": self.zoom,
                "municipalities": [{"id": m, "name": n} for m, n in self.municipalities]}


# Seasons follow the India Meteorological Department's seasons, using the ones whose satellite
# imagery is not dominated by monsoon cloud in that city.
_IMD_PRE = ((3, 1), (5, 31), "Pre-monsoon")
_IMD_POST = ((10, 1), (12, 31), "Post-monsoon")
_IMD_WINTER = ((1, 1), (2, 28), "Winter")

CITIES: dict[str, City] = {
    "mumbai": City(
        id="mumbai", name="Mumbai", region_label="Mumbai, Thane and Mira-Bhayandar",
        municipalities=(("mumbai", "Mumbai"), ("thane", "Thane"), ("mira_bhayandar", "Mira-Bhayandar")),
        center=(72.8777, 19.0760), zoom=10.8,
        openaq_bbox=(72.77, 18.89, 73.12, 19.40),
        # coastal Mumbai at the ~10:30 IST Landsat overpass is >= ~22 °C even over water in the dry seasons
        lst_qc_min_c=20.0,
        seasons={"pre": _IMD_PRE, "post": _IMD_POST},
        knowledge_places=("Mumbai", "Thane", "Mira-Bhayandar"),
        kb={"ndvi_season": "ndvi_season_mumbai", "air_sources": "mumbai_air_sources",
            "air_season": "mumbai_air_seasonality", "climate": "mumbai_climate",
            "action_plan": "mumbai_climate_action_plan"},
        sources=("OpenStreetMap municipal boundaries (see data/boundaries/README.md)",),
    ),
    "delhi": City(
        id="delhi", name="Delhi", region_label="Delhi (National Capital Territory)",
        municipalities=(("delhi", "Delhi"),),
        center=(77.1025, 28.6448), zoom=10.2,
        openaq_bbox=(76.74, 28.30, 77.45, 28.98),
        # winter mornings are the coldest clear-sky surfaces in Delhi's windows (~15-20 °C over water)
        lst_qc_min_c=10.0,
        seasons={"pre": _IMD_PRE, "post": _IMD_POST},
        knowledge_places=("Delhi", "New Delhi"),
        kb={"air_sources": "delhi_air_sources", "air_season": "delhi_air_seasonality",
            "climate": "delhi_climate", "action_plan": "delhi_heat_action_plan"},
        sources=("Delhi boundary: DataMeet Municipal Spatial Data (CC BY-SA 2.5 IN)",),
        subdir="delhi",
    ),
    "bengaluru": City(
        id="bengaluru", name="Bengaluru", region_label="Bengaluru (BBMP area)",
        municipalities=(("bengaluru", "Bengaluru"),),
        center=(77.5946, 12.9716), zoom=10.8,
        openaq_bbox=(77.36, 12.73, 77.88, 13.24),
        # ~900 m elevation: the coolest clear surfaces (lakes, winter) stay well above 15 °C at overpass
        lst_qc_min_c=15.0,
        # Oct-Dec is the north-east monsoon here (cloudy), so the clear dry season Jan-Feb is used
        seasons={"winter": _IMD_WINTER, "pre": _IMD_PRE},
        knowledge_places=("Bengaluru", "Bangalore"),
        kb={"air_sources": "bengaluru_air_sources", "climate": "bengaluru_climate",
            "lakes": "bengaluru_lakes"},
        sources=("BBMP wards (2022 delimitation, KSRSAC) via DataMeet Municipal Spatial Data (CC BY-SA 2.5 IN)",),
        subdir="bengaluru",
    ),
}
DEFAULT_CITY = os.getenv("GEOSENSE_DEFAULT_CITY", "mumbai")

_CURRENT: ContextVar[str] = ContextVar("geosense_city", default=DEFAULT_CITY)


class UnknownCity(KeyError):
    pass


def get_city(city_id: str | None = None) -> City:
    cid = (city_id or _CURRENT.get() or DEFAULT_CITY).strip().lower()
    cid = {"new_delhi": "delhi", "new-delhi": "delhi", "bangalore": "bengaluru"}.get(cid, cid)
    if cid not in CITIES:
        raise UnknownCity(cid)
    return CITIES[cid]


def current_city_id() -> str:
    return get_city().id


@contextmanager
def use_city(city_id: str) -> Iterator[City]:
    """Work on one city inside this block (scripts, background threads, per-request)."""
    city = get_city(city_id)
    token = _CURRENT.set(city.id)
    try:
        yield city
    finally:
        _CURRENT.reset(token)


def set_city(city_id: str):
    """Set the city for the rest of this context (returns a token for _CURRENT.reset)."""
    return _CURRENT.set(get_city(city_id).id)


def reset_city(token) -> None:
    _CURRENT.reset(token)


def city_for_point(lon: float, lat: float) -> str | None:
    """The city whose study region contains the point (None if none does)."""
    from app.services.municipality_boundaries import city_region_or_none
    from shapely.geometry import Point

    p = Point(lon, lat)
    for cid in CITIES:
        geom = city_region_or_none(cid)
        if geom is not None and geom.bounds[0] <= lon <= geom.bounds[2] and geom.bounds[1] <= lat <= geom.bounds[3] \
                and geom.covers(p):
            return cid
    return None


def available_cities() -> list[str]:
    """Cities whose boundaries exist (the rest of the data may still be being generated)."""
    out = []
    for cid, c in CITIES.items():
        if all((c.data_dir / "boundaries" / f"{m}.geojson").is_file() for m, _ in c.municipalities):
            out.append(cid)
    return out


class CityPath(os.PathLike):
    """A file or folder inside the CURRENT city's data folder, resolved every time it is used.

    Behaves like a pathlib.Path (`/`, .exists(), .read_text(), .mkdir(), os.fspath, ...), so a
    module-level constant such as MANIFEST_PATH = city_path("surfaces", "manifest.json") always
    points at the manifest of the city being worked on.
    """

    __slots__ = ("_parts",)

    def __init__(self, *parts: str):
        self._parts = parts

    def resolve_path(self) -> Path:
        return get_city().data_dir.joinpath(*self._parts)

    def __fspath__(self) -> str:
        return str(self.resolve_path())

    def __truediv__(self, other) -> Path:
        return self.resolve_path() / other

    def __getattr__(self, name):
        return getattr(self.resolve_path(), name)

    def __str__(self) -> str:
        return str(self.resolve_path())

    def __repr__(self) -> str:
        return f"CityPath({'/'.join(self._parts)!r} -> {self.resolve_path()})"

    def __eq__(self, other) -> bool:
        return Path(self) == Path(other) if isinstance(other, (str, os.PathLike)) else NotImplemented

    def __hash__(self) -> int:
        return hash(self.resolve_path())


def city_path(*parts: str) -> CityPath:
    return CityPath(*parts)


def pop_city_arg(argv: list[str] | None = None) -> str:
    """Take `--city <id>` (or --city=<id>) out of the command line; default = DEFAULT_CITY."""
    import sys

    argv = sys.argv if argv is None else argv
    for i, a in enumerate(list(argv)):
        if a == "--city" and i + 1 < len(argv):
            cid = argv[i + 1]
            del argv[i:i + 2]
            return get_city(cid).id
        if a.startswith("--city="):
            del argv[i]
            return get_city(a.split("=", 1)[1]).id
    return get_city().id


def run_script_for_city(main) -> int:
    """`if __name__ == "__main__": raise SystemExit(run_script_for_city(main))` — every pipeline
    script takes --city mumbai|delhi|bengaluru (default mumbai) and runs main() for that city."""
    cid = pop_city_arg()
    with use_city(cid) as city:
        print(f"[{city.name}] {city.region_label}")
        return main()

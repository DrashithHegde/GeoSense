"""Shared quality-control thresholds (single source of truth).

Landsat C2 L2 surface temperature below a city's plausible minimum at the ~10:30 IST overpass is
residual cloud / cloud-edge contamination. Such pixels are hidden in the visualisation and
excluded from cell statistics; a clicked raw pixel is still returned with a QC flag, never
silently altered. The threshold is per city (app/core/cities.py: lst_qc_min_c): coastal Mumbai is
>= ~22 °C even over water in its dry seasons, while Delhi's winter surfaces can be much cooler.
"""
from app.core.cities import get_city


def lst_qc_min_c(city_id: str | None = None) -> float:
    """Lowest plausible clear-sky LST (°C) for the city in use."""
    return get_city(city_id).lst_qc_min_c

"""Landsat 8/9 Collection 2 Level-2 building blocks shared by the LST layer and the history.

* LST_DATASETS and the 45-day composite window
* mask_landsat_l2 (QA_PIXEL fill / cloud / shadow mask) and add_lst_celsius (ST_B10 -> °C, USGS
  scale and offset)
* source_context: the provenance record of a composite window

The layer itself is built by app/services/surfaces/lst_surface.py.
"""
from __future__ import annotations

from datetime import datetime

import ee

LST_DATASETS = ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2")
COMPOSITE_WINDOW_DAYS = 45


def mask_landsat_l2(image: ee.Image) -> ee.Image:
    # QA_PIXEL bits (Landsat C2): 0=fill, 3=cloud, 4=cloud shadow
    # Keep masking conservative but not overly strict to retain usable thermal pixels.
    qa = image.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 0).eq(0)
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 4).eq(0))
    )
    return image.updateMask(clear)


def add_lst_celsius(image: ee.Image) -> ee.Image:
    # Landsat C2 L2 ST_B10: Kelvin = DN * 0.00341802 + 149.0
    # Celsius = Kelvin - 273.15
    lst_c = image.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
    return image.addBands(lst_c)


def source_context(start_date: str, end_date: str) -> dict:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        raise ValueError(
            f"LST history uses the existing fixed {COMPOSITE_WINDOW_DAYS}-day composite window; "
            f"received {start_date} to {end_date}"
        )
    return {
        "datasets": list(LST_DATASETS),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": COMPOSITE_WINDOW_DAYS,
        "composite": "median",
        "scale_m": 30,
        "thermal_band": "ST_B10",
        "unit": "celsius",
        "qa_mask": "QA_PIXEL bits 0, 3, and 4",
        "temperature_conversion": "ST_B10 * 0.00341802 + 149.0 - 273.15",
    }

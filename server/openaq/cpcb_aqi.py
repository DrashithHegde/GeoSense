"""Indian CPCB AQI calculation from pollutant concentrations.

Implements CPCB National Air Quality Index (2014) breakpoints.
Station AQI = max of all computable pollutant sub-indices.
No fabrication: if averaging period data is unavailable, that pollutant is skipped.
Units: pm25/pm10/no2/so2/o3 in ug/m3; co in ug/m3 (internally converted to mg/m3).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# CPCB 24-h breakpoints: (C_low, C_high, I_low, I_high)
CPCB_BREAKPOINTS: Dict[str, list] = {
    "pm25": [
        (0,    30,    0,   50), (31,   60,   51,  100),
        (61,   90,  101,  200), (91,  120,  201,  300),
        (121, 250,  301,  400), (251, 500,  401,  500),
    ],
    "pm10": [
        (0,    50,    0,   50), (51,  100,   51,  100),
        (101, 250,  101,  200), (251, 350,  201,  300),
        (351, 430,  301,  400), (431, 600,  401,  500),
    ],
    "no2": [
        (0,    40,    0,   50), (41,   80,   51,  100),
        (81,  180,  101,  200), (181, 280,  201,  300),
        (281, 400,  301,  400), (401, 800,  401,  500),
    ],
    "so2": [
        (0,    40,    0,   50), (41,   80,   51,  100),
        (81,  380,  101,  200), (381, 800,  201,  300),
        (801, 1600, 301,  400), (1601, 2000, 401, 500),
    ],
    "o3": [
        (0,    50,    0,   50), (51,  100,   51,  100),
        (101, 168,  101,  200), (169, 208,  201,  300),
        (209, 748,  301,  400), (749, 1000, 401,  500),
    ],
    # CO breakpoints use mg/m3 in CPCB standard
    "co": [
        (0,    1.0,   0,   50), (1.1,  2.0,  51,  100),
        (2.1, 10.0, 101,  200), (10.1, 17.0, 201, 300),
        (17.1, 34.0, 301, 400), (34.1, 50.0, 401, 500),
    ],
}

CO_UGM3_TO_MGM3 = 1.0 / 1000.0


def _sub_index(concentration: float, breakpoints: list) -> Optional[float]:
    """Linear interpolation within CPCB breakpoint table."""
    for c_low, c_high, i_low, i_high in breakpoints:
        if c_low <= concentration <= c_high:
            return i_low + (concentration - c_low) * (i_high - i_low) / (c_high - c_low)
    return None


def compute_pollutant_sub_indices(
    pollutants: Dict[str, float]
) -> Dict[str, Optional[float]]:
    """Compute per-pollutant CPCB sub-indices.

    pm25/pm10/no2/so2/o3 expected in ug/m3.
    co expected in ug/m3 (converted to mg/m3 internally for CPCB breakpoints).
    Returns dict of param -> sub_index or None.
    """
    sub_indices: Dict[str, Optional[float]] = {}
    for param, bpts in CPCB_BREAKPOINTS.items():
        conc = pollutants.get(param)
        if conc is None:
            sub_indices[param] = None
            continue
        if param == "co":
            conc = conc * CO_UGM3_TO_MGM3
        sub_indices[param] = _sub_index(conc, bpts)
    return sub_indices


def compute_station_cpcb_aqi(
    pollutants: Dict[str, float]
) -> Tuple[Optional[int], Optional[str], Dict[str, Optional[float]]]:
    """Compute station-level CPCB AQI.

    Returns (aqi, dominant_pollutant, sub_indices).
    aqi is None if no valid sub-index can be computed.
    """
    sub_indices = compute_pollutant_sub_indices(pollutants)
    valid = {p: v for p, v in sub_indices.items() if v is not None}
    if not valid:
        return None, None, sub_indices
    dominant = max(valid, key=lambda p: valid[p])
    aqi = int(round(valid[dominant]))
    return aqi, dominant, sub_indices

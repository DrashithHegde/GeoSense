"""Season definitions for GeoSense history (per city).

Monsoon cloud hides optical and thermal imagery, so history uses each city's dry seasons
(India Meteorological Department seasons; app/core/cities.py):
  Mumbai, Delhi : pre-monsoon 1 Mar - 31 May, post-monsoon 1 Oct - 31 Dec
  Bengaluru     : winter 1 Jan - 28 Feb, pre-monsoon 1 Mar - 31 May
                  (Oct-Dec is Bengaluru's cloudy north-east monsoon)
Comparisons are only made between the SAME season in different years (compatible windows,
similar sun angle and phenology). A season still in progress is marked partial and, for its
year-on-year comparison, a "matched" window with the same day range one year earlier is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.core.cities import get_city

FIRST_YEAR = 2023
MIN_PARTIAL_DAYS = 30


def windows(city_id: str | None = None) -> dict[str, tuple[tuple[int, int], tuple[int, int], str]]:
    return get_city(city_id).seasons


@dataclass(frozen=True)
class Season:
    key: str          # 2024-pre, 2026-post, 2025-post-matched
    kind: str         # pre | post | winter
    year: int
    start: date
    end: date         # inclusive
    partial: bool = False
    matched_for: str | None = None   # set on a matched window: the partial season it serves
    name: str = ""

    @property
    def label(self) -> str:
        name = self.name or self.kind
        if self.matched_for:
            return f"{name} {self.year} ({self.start:%d %b}-{self.end:%d %b}, matched)"
        return f"{name} {self.year}" + (f" (to {self.end:%d %b})" if self.partial else "")

    @property
    def end_exclusive(self) -> str:
        return (self.end + timedelta(days=1)).isoformat()


def seasons(today: date | None = None, first_year: int = FIRST_YEAR, city_id: str | None = None) -> list[Season]:
    today = today or date.today()
    win = windows(city_id)
    out: list[Season] = []
    for y in range(first_year, today.year + 1):
        for kind, ((sm, sd), (em, ed), name) in sorted(win.items(), key=lambda kv: kv[1][0]):
            start, end = date(y, sm, sd), date(y, em, ed)
            if start > today:
                continue
            if end < today:
                out.append(Season(f"{y}-{kind}", kind, y, start, end, name=name))
                continue
            last = today - timedelta(days=1)
            if (last - start).days + 1 < MIN_PARTIAL_DAYS:
                continue  # too early in the season to be meaningful
            out.append(Season(f"{y}-{kind}", kind, y, start, last, partial=True, name=name))
            if y - 1 >= first_year:
                out.append(Season(f"{y - 1}-{kind}-matched", kind, y - 1, date(y - 1, sm, sd),
                                  date(y - 1, last.month, min(last.day, 28 if last.month == 2 else last.day)),
                                  matched_for=f"{y}-{kind}", name=name))
    return out


def comparable_previous(key: str, available: dict[str, Season]) -> Season | None:
    """The window to compare a season with: same season one year earlier (matched if partial)."""
    s = available.get(key)
    if not s or s.matched_for:
        return None
    if s.partial:
        return available.get(f"{s.year - 1}-{s.kind}-matched")
    return available.get(f"{s.year - 1}-{s.kind}")

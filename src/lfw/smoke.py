"""Smoke screening sector from hourly wind (MVP §6.4). Pure functions, no network.

This is a SCREENING SECTOR, not a dispersion model and not a pollution forecast. It marks the
area downwind of the site where smoke may travel, so a person knows which places to check first.

Conventions: wind direction is the compass bearing the wind comes FROM (Open-Meteo
`wind_direction_10m`). Smoke travels TOWARD (from + 180) % 360. Bearings are clockwise from north.
"""

from __future__ import annotations

import math
from datetime import datetime

from shapely.geometry import Point, Polygon, mapping
from shapely.ops import unary_union

from lfw.config import (
    CALM_MEAN_WIND_MS,
    CALM_RADIUS_KM,
    LOW_WIND_MS,
    SMOKE_HALF_ANGLE_DEG,
    SMOKE_HALF_ANGLE_LOW_WIND_DEG,
    SMOKE_LENGTH_KM,
)
from lfw.geo import LocalProjection
from lfw.models import SmokeZone, WindHour

ARC_STEP_DEG = 2  # polygon vertex spacing along the sector arc (drawing detail only)

SCREENING_NOTE = "Screening sector from wind direction only. It is not a pollution forecast."


def toward_deg(from_deg: float) -> int:
    """Direction smoke travels toward, for wind coming FROM `from_deg`."""
    return int(round(from_deg + 180)) % 360


def half_angle_deg(speed_ms: float) -> int:
    """Wider sector in light wind, because the direction is less stable."""
    return SMOKE_HALF_ANGLE_LOW_WIND_DEG if speed_ms < LOW_WIND_MS else SMOKE_HALF_ANGLE_DEG


def sector_m(toward: float, half_angle: float, length_m: float) -> Polygon:
    """Wedge with its apex at (0, 0) in local metres (x east, y north)."""
    pts = [(0.0, 0.0)]
    a = toward - half_angle
    while a <= toward + half_angle + 1e-9:
        r = math.radians(a)
        pts.append((length_m * math.sin(r), length_m * math.cos(r)))
        a += ARC_STEP_DEG
    r = math.radians(toward + half_angle)
    pts.append((length_m * math.sin(r), length_m * math.cos(r)))
    return Polygon(pts)


def smoke_zone(
    origin_lat: float,
    origin_lon: float,
    hours: list[WindHour],
    computed_utc: datetime,
    wind_point: tuple[float, float] | None = None,
) -> SmokeZone:
    """Union of the hourly sectors, or a calm circle when the mean speed is below CALM_MEAN_WIND_MS."""
    if not hours:
        raise ValueError("smoke_zone needs at least one wind hour")
    proj = LocalProjection(origin_lat, origin_lon)
    toward = [toward_deg(h.from_deg) for h in hours]
    halves = [half_angle_deg(h.speed_ms) for h in hours]
    mean_speed = sum(h.speed_ms for h in hours) / len(hours)
    calm = mean_speed < CALM_MEAN_WIND_MS
    if calm:
        geom_m = Point(0.0, 0.0).buffer(CALM_RADIUS_KM * 1000.0, quad_segs=32)
        length_km = CALM_RADIUS_KM
    else:
        length_m = SMOKE_LENGTH_KM * 1000.0
        geom_m = unary_union([sector_m(t, ha, length_m) for t, ha in zip(toward, halves, strict=True)])
        length_km = SMOKE_LENGTH_KM
    return SmokeZone(
        computed_utc=computed_utc,
        wind_hours=hours,
        toward_deg=toward,
        half_angle_deg=max(halves),
        half_angles_deg=halves,
        length_km=length_km,
        calm=calm,
        mean_speed_ms=round(mean_speed, 2),
        geometry_geojson=mapping(proj.inverse(geom_m)),
        wind_point_lat=wind_point[0] if wind_point else None,
        wind_point_lon=wind_point[1] if wind_point else None,
    )


def compass(deg: float) -> str:
    """16-point compass name, for human-readable text (e.g. 270 -> 'W')."""
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]

"""Local geometry. Pure functions, no network calls (CLAUDE.md §8).

Distances under LOCAL_PROJECTION_MAX_KM use a local equirectangular projection around an origin
(CLAUDE.md §3): x = R * dlon * cos(lat0), y = R * dlat, with angles in radians.
"""

from __future__ import annotations

import math

import shapely
from shapely.geometry.base import BaseGeometry

from lfw.config import EARTH_RADIUS_M


class LocalProjection:
    """Equirectangular projection around (lat0, lon0). Units: metres. Input order: (lon, lat)."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0 = lat0
        self.lon0 = lon0
        self._ky = EARTH_RADIUS_M * math.pi / 180.0
        self._kx = self._ky * math.cos(math.radians(lat0))

    def forward(self, geom: BaseGeometry) -> BaseGeometry:
        def fwd(c):
            out = c.copy()
            out[:, 0] = (c[:, 0] - self.lon0) * self._kx
            out[:, 1] = (c[:, 1] - self.lat0) * self._ky
            return out

        return shapely.transform(geom, fwd)

    def inverse(self, geom: BaseGeometry) -> BaseGeometry:
        def inv(c):
            out = c.copy()
            out[:, 0] = c[:, 0] / self._kx + self.lon0
            out[:, 1] = c[:, 1] / self._ky + self.lat0
            return out

        return shapely.transform(geom, inv)

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self._kx, (lat - self.lat0) * self._ky)


def projection_for(geom_lonlat: BaseGeometry) -> LocalProjection:
    """Projection centred on the geometry's lon/lat centroid."""
    c = geom_lonlat.centroid
    return LocalProjection(lat0=c.y, lon0=c.x)


def area_ha(geom_lonlat: BaseGeometry) -> float:
    proj = projection_for(geom_lonlat)
    return proj.forward(geom_lonlat).area / 10_000.0


def centroid_latlon(geom_lonlat: BaseGeometry) -> tuple[float, float]:
    """Area-weighted centroid computed in local metres, returned as (lat, lon)."""
    proj = projection_for(geom_lonlat)
    c = proj.inverse(proj.forward(geom_lonlat).centroid)
    return (c.y, c.x)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

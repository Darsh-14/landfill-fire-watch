"""Local geometry. Pure functions, no network calls (CLAUDE.md §8).

Distances under LOCAL_PROJECTION_MAX_KM use a local equirectangular projection around an origin
(CLAUDE.md §3): x = R * dlon * cos(lat0), y = R * dlat, with angles in radians.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import shapely
from shapely.geometry import Point
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


def pixel_half_size_m(scan_km: float, track_km: float) -> float:
    """MVP §6.1 step 2: r = max(scan_km, track_km) * 1000 / 2."""
    return max(scan_km, track_km) * 1000.0 / 2.0


@dataclass(frozen=True)
class SiteShape:
    """A site outline with its local projection (centred on the site centroid, MVP §6.1 step 1)."""

    site_id: str
    polygon_lonlat: BaseGeometry
    proj: LocalProjection
    polygon_m: BaseGeometry
    centroid_lat: float
    centroid_lon: float
    bounds_lonlat: tuple[float, float, float, float]


def site_shape(site_id: str, polygon_lonlat: BaseGeometry) -> SiteShape:
    lat, lon = centroid_latlon(polygon_lonlat)
    proj = LocalProjection(lat, lon)
    return SiteShape(
        site_id=site_id,
        polygon_lonlat=polygon_lonlat,
        proj=proj,
        polygon_m=proj.forward(polygon_lonlat),
        centroid_lat=lat,
        centroid_lon=lon,
        bounds_lonlat=polygon_lonlat.bounds,
    )


def distance_to_site_m(shape: SiteShape, lat: float, lon: float) -> float:
    """Distance in metres from a point to the outline; 0 if the point is inside."""
    return shape.polygon_m.distance(Point(shape.proj.xy(lat, lon)))


def near_bounds(shape: SiteShape, lat: float, lon: float, radius_m: float) -> bool:
    """Cheap pre-filter: is the point within radius_m (plus 50%) of the outline's bounding box?"""
    w, s, e, n = shape.bounds_lonlat
    dlat = 1.5 * radius_m / (EARTH_RADIUS_M * math.pi / 180.0)
    dlon = dlat / max(math.cos(math.radians(shape.centroid_lat)), 0.01)
    return (s - dlat) <= lat <= (n + dlat) and (w - dlon) <= lon <= (e + dlon)


def matches(shape: SiteShape, lat: float, lon: float, scan_km: float, track_km: float,
            margin_m: float) -> float | None:
    """MVP §6.1 steps 2-4. The point is inside the outline buffered by r + margin exactly when its
    distance to the outline is at most r + margin. Returns that distance, or None if no match."""
    radius = pixel_half_size_m(scan_km, track_km) + margin_m
    if not near_bounds(shape, lat, lon, radius):
        return None
    d = distance_to_site_m(shape, lat, lon)
    return d if d <= radius else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

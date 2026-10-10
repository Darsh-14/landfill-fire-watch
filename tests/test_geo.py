"""Geometry tests. P0 covers the projection used for site areas; P1 adds the matching tests."""

import math

from shapely.geometry import Polygon

from lfw import geo
from lfw.config import EARTH_RADIUS_M


def _square_lonlat(lat0: float, lon0: float, side_m: float) -> Polygon:
    """A square of the given side in local metres, converted to lon/lat by the inverse projection."""
    proj = geo.LocalProjection(lat0, lon0)
    h = side_m / 2
    return proj.inverse(Polygon([(-h, -h), (h, -h), (h, h), (-h, h)]))


def test_area_of_one_km_square_is_100_ha():
    sq = _square_lonlat(10.0, 76.0, 1000.0)
    assert abs(geo.area_ha(sq) - 100.0) < 0.5


def test_centroid_round_trip():
    sq = _square_lonlat(19.07, 72.93, 500.0)
    lat, lon = geo.centroid_latlon(sq)
    assert abs(lat - 19.07) < 1e-6 and abs(lon - 72.93) < 1e-6


def test_projection_error_under_one_percent_at_10_km():
    lat0, lon0 = 28.62, 77.33
    proj = geo.LocalProjection(lat0, lon0)
    for bearing_deg in (0, 45, 90, 135, 225):
        b = math.radians(bearing_deg)
        dlat = math.degrees(10_000 * math.cos(b) / EARTH_RADIUS_M)
        dlon = math.degrees(10_000 * math.sin(b) / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
        lat, lon = lat0 + dlat, lon0 + dlon
        x, y = proj.xy(lat, lon)
        planar = (x * x + y * y) ** 0.5
        great_circle = geo.haversine_m(lat0, lon0, lat, lon)
        assert abs(planar - great_circle) / great_circle < 0.01

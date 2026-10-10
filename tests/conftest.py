"""Shared test helpers. Synthetic geometry here is test data only, never shipped as site data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from lfw import geo
from lfw.models import Detection

FIXTURES = Path(__file__).parent / "fixtures"


def square_site(site_id: str, lat0: float, lon0: float, side_m: float) -> geo.SiteShape:
    """A square outline of side_m metres centred on (lat0, lon0)."""
    proj = geo.LocalProjection(lat0, lon0)
    h = side_m / 2
    poly = proj.inverse(Polygon([(-h, -h), (h, -h), (h, h), (-h, h)]))
    return geo.site_shape(site_id, poly)


def offset_point(shape: geo.SiteShape, east_m: float, north_m: float) -> tuple[float, float]:
    """(lat, lon) of a point east_m / north_m metres from the site centroid."""
    from shapely.geometry import Point

    p = shape.proj.inverse(Point(east_m, north_m))
    return p.y, p.x


def det(
    *,
    t: str,
    lat: float = 10.0,
    lon: float = 76.0,
    tier: str = "nominal",
    frp: float | None = 2.0,
    source: str = "VIIRS_SNPP_SP",
    satellite: str = "N",
    site_id: str | None = "s1",
    mode: str = "replay",
    scan_km: float = 0.4,
    track_km: float = 0.4,
    static: bool = False,
) -> Detection:
    acq = datetime.fromisoformat(t).replace(tzinfo=UTC)
    return Detection(
        key=f"{source}|{acq:%Y-%m-%d}|{acq:%H%M}|{lat:.4f}|{lon:.4f}",
        source=source,
        satellite=satellite,
        instrument="VIIRS" if source.startswith("VIIRS") else "MODIS",
        lat=lat,
        lon=lon,
        acq_utc=acq,
        confidence_raw={"low": "l", "nominal": "n", "high": "h"}[tier],
        confidence_tier="low" if static else tier,
        frp_mw=frp,
        scan_km=scan_km,
        track_km=track_km,
        daynight="N",
        type_code=2 if static else 0,
        static_source=static,
        site_id=site_id,
        match_distance_m=0.0 if site_id else None,
        mode=mode,
    )


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read

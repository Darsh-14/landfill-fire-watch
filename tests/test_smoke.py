"""Smoke screening sector and wind parsing (MVP §6.4)."""

import json
from datetime import UTC, datetime

import pytest
from shapely.geometry import Point, shape

from conftest import FIXTURES
from lfw import geo, smoke, wind
from lfw.models import WindHour

T0 = datetime(2023, 3, 2, 16, 0, tzinfo=UTC)
LAT0, LON0 = 10.0, 76.0


def wh(from_deg: int, speed: float, hour: int = 16) -> WindHour:
    return WindHour(time_utc=T0.replace(hour=hour), speed_ms=speed, from_deg=from_deg)


def point_at(bearing_deg: float, dist_m: float) -> Point:
    """(lon, lat) point at a compass bearing and distance from the origin."""
    import math

    proj = geo.LocalProjection(LAT0, LON0)
    b = math.radians(bearing_deg)
    return proj.inverse(Point(dist_m * math.sin(b), dist_m * math.cos(b)))


def test_wind_from_270_blows_smoke_toward_90():
    assert smoke.toward_deg(270) == 90


def test_wind_from_350_blows_smoke_toward_170():
    assert smoke.toward_deg(350) == 170


def test_wind_from_0_and_180_wrap():
    assert smoke.toward_deg(0) == 180 and smoke.toward_deg(180) == 0


def test_mean_speed_under_1_ms_gives_calm_circle():
    z = smoke.smoke_zone(LAT0, LON0, [wh(90, 0.6), wh(100, 0.9, 17)], T0)
    assert z.calm and z.length_km == 2.0
    g = shape(z.geometry_geojson)
    assert g.covers(point_at(0, 1900)) and g.covers(point_at(200, 1900)) and not g.covers(point_at(0, 2100))


def test_speed_under_2_ms_gives_45_degree_half_angle():
    z = smoke.smoke_zone(LAT0, LON0, [wh(270, 1.5)], T0)
    assert not z.calm and z.half_angle_deg == 45 and z.half_angles_deg == [45]
    g = shape(z.geometry_geojson)
    assert g.covers(point_at(90 + 40, 5000)) and not g.covers(point_at(90 + 50, 5000))
    z2 = smoke.smoke_zone(LAT0, LON0, [wh(270, 3.0)], T0)
    assert z2.half_angle_deg == 30
    g2 = shape(z2.geometry_geojson)
    assert g2.covers(point_at(90 + 25, 5000)) and not g2.covers(point_at(90 + 35, 5000))


def test_sector_length_is_10_km():
    g = shape(smoke.smoke_zone(LAT0, LON0, [wh(270, 3.0)], T0).geometry_geojson)
    assert g.covers(point_at(90, 9900)) and not g.covers(point_at(90, 10100))


def test_zone_is_union_of_hourly_sectors():
    hours = [wh(270, 3.0, 16), wh(0, 3.0, 17)]  # toward 90 (east), then toward 180 (south)
    z = smoke.smoke_zone(LAT0, LON0, hours, T0)
    assert z.toward_deg == [90, 180]
    g = shape(z.geometry_geojson)
    assert g.covers(point_at(90, 5000)) and g.covers(point_at(180, 5000))
    assert not g.covers(point_at(270, 5000)) and not g.covers(point_at(0, 5000))
    singles = [shape(smoke.smoke_zone(LAT0, LON0, [h], T0).geometry_geojson) for h in hours]
    assert abs(g.area - singles[0].union(singles[1]).area) < 1e-12


def test_empty_wind_is_an_error():
    with pytest.raises(ValueError):
        smoke.smoke_zone(LAT0, LON0, [], T0)


def test_compass_names():
    assert smoke.compass(0) == "N" and smoke.compass(90) == "E" and smoke.compass(250) == "WSW"


@pytest.mark.parametrize("name", ["openmeteo_archive_brahmapuram_2023-03-02.json", "openmeteo_forecast_brahmapuram.json"])
def test_parse_open_meteo_fixtures(name):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    hours, (glat, glon) = wind.parse_hourly(payload)
    assert len(hours) == 24 and all(h.time_utc.tzinfo is UTC for h in hours)
    assert (glat, glon) == (payload["latitude"], payload["longitude"])
    assert hours[0].from_deg == payload["hourly"]["wind_direction_10m"][0]


def test_archive_fixture_first_hour_values():
    payload = json.loads((FIXTURES / "openmeteo_archive_brahmapuram_2023-03-02.json").read_text(encoding="utf-8"))
    hours, _ = wind.parse_hourly(payload)
    assert hours[0].time_utc == datetime(2023, 3, 2, 0, 0, tzinfo=UTC)
    assert hours[0].speed_ms == 1.14 and hours[0].from_deg == 38


def test_parser_rejects_wrong_units():
    payload = json.loads((FIXTURES / "openmeteo_forecast_brahmapuram.json").read_text(encoding="utf-8"))
    payload["hourly_units"]["wind_speed_10m"] = "km/h"
    with pytest.raises(wind.WindFormatError):
        wind.parse_hourly(payload)


def test_replay_hours_are_detection_hour_plus_6():
    hours = [wh(90, 2.0, h) for h in range(24)]
    sel = wind.replay_hours(hours, [datetime(2023, 3, 2, 16, 35, tzinfo=UTC)], extra=6)
    assert [h.time_utc.hour for h in sel] == [16, 17, 18, 19, 20, 21, 22]


def test_next_hours_live():
    hours = [wh(90, 2.0, h) for h in range(24)]
    sel = wind.next_hours(hours, datetime(2023, 3, 2, 10, 20, tzinfo=UTC), 6)
    assert [h.time_utc.hour for h in sel] == [10, 11, 12, 13, 14, 15]

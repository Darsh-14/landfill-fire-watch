"""Tier mapping, static sources, nearest-site matching, stable keys (MVP §6.1, §6.2)."""

import pytest

from conftest import det, offset_point, square_site
from lfw import detect, firms


@pytest.mark.parametrize("raw,tier", [("l", "low"), ("n", "nominal"), ("h", "high"), ("H", "high")])
def test_viirs_letters(raw, tier):
    assert detect.tier("VIIRS", raw) == tier


@pytest.mark.parametrize(
    "raw,tier",
    [("0", "low"), ("29", "low"), ("30", "nominal"), ("79", "nominal"), ("80", "high"), ("100", "high")],
)
def test_modis_numbers(raw, tier):
    assert detect.tier("MODIS", raw) == tier


def test_unknown_confidence_is_an_error():
    with pytest.raises(ValueError):
        detect.tier("VIIRS", "x")
    with pytest.raises(ValueError):
        detect.tier("MODIS", "101")


def test_static_source_type_becomes_low():
    header = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight,type"
    csv_text = header + "\n10.0,76.0,330.0,0.4,0.4,2023-03-01,2014,N,VIIRS,h,2,295.0,12.0,N,2\n"
    (d,) = firms.parse_csv(csv_text, "VIIRS_SNPP_SP", "replay")
    assert d.confidence_raw == "h" and d.confidence_tier == "low" and d.static_source


def test_nearest_site_wins():
    a = square_site("a", 10.0, 76.0, 200.0)
    b_lat, b_lon = offset_point(a, 600.0, 0.0)
    b = square_site("b", b_lat, b_lon, 200.0)
    lat, lon = offset_point(a, 250.0, 0.0)  # 150 m from a's edge, 250 m from b's edge
    d = det(t="2023-03-02T19:55", lat=lat, lon=lon, site_id=None)
    m = detect.assign(d, {"a": a, "b": b})
    assert m is not None and m.site_id == "a" and abs(m.match_distance_m - 150.0) < 1.0
    lat2, lon2 = offset_point(a, 350.0, 0.0)  # 250 m from a, 150 m from b
    m2 = detect.assign(det(t="2023-03-02T19:55", lat=lat2, lon=lon2, site_id=None), {"a": a, "b": b})
    assert m2 is not None and m2.site_id == "b"


def test_no_site_in_range():
    a = square_site("a", 10.0, 76.0, 200.0)
    lat, lon = offset_point(a, 2000.0, 0.0)
    assert detect.assign(det(t="2023-03-02T19:55", lat=lat, lon=lon, site_id=None), {"a": a}) is None


def test_key_is_stable_on_reingest(fixture_text):
    text = fixture_text("firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv")
    first = firms.parse_csv(text, "VIIRS_SNPP_SP", "replay")
    second = firms.parse_csv(text, "VIIRS_SNPP_SP", "replay")
    assert [d.key for d in first] == [d.key for d in second]
    site = square_site("s", first[0].lat, first[0].lon, 50_000.0)  # large test square covering all rows
    matched = detect.match(first + second, {"s": site})
    assert len(matched) == len(first)

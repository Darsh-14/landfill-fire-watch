"""FIRMS parser tests against the real fixtures (CLAUDE.md rule 3)."""

from datetime import UTC, datetime

import pytest
import yaml

from conftest import FIXTURES
from lfw import firms

MANIFEST = yaml.safe_load((FIXTURES / "MANIFEST.yaml").read_text(encoding="utf-8"))

CASES = [
    ("firms_live_VIIRS_SNPP_NRT_punjab.csv", "VIIRS_SNPP_NRT", "live"),
    ("firms_live_MODIS_NRT_punjab.csv", "MODIS_NRT", "live"),
    ("firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv", "VIIRS_SNPP_SP", "replay"),
    ("firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv", "MODIS_SP", "replay"),
]


@pytest.mark.parametrize("name,source,mode", CASES)
def test_parses_every_row_of_each_fixture(fixture_text, name, source, mode):
    dets = firms.parse_csv(fixture_text(name), source, mode)
    assert len(dets) == MANIFEST[name]["data_rows"]
    assert all(d.source == source and d.mode == mode for d in dets)
    assert len({d.key for d in dets}) == len(dets)
    assert all(d.acq_utc.tzinfo is UTC for d in dets)


@pytest.mark.parametrize("name,source,mode", CASES)
def test_type_code_only_in_archive(fixture_text, name, source, mode):
    dets = firms.parse_csv(fixture_text(name), source, mode)
    if source.endswith("_NRT"):
        assert all(d.type_code is None for d in dets)
    else:
        assert all(d.type_code is not None for d in dets)


def test_acq_time_without_zero_padding(fixture_text):
    dets = firms.parse_csv(fixture_text("firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv"), "MODIS_SP", "replay")
    by_time = {d.acq_utc: d for d in dets}
    d = by_time[datetime(2023, 3, 3, 4, 50, tzinfo=UTC)]  # fixture acq_time "450"
    assert d.key == "MODIS_SP|2023-03-03|0450|9.9934|76.3640"
    assert d.satellite == "Terra" and d.version == "61.03"


def test_tiers_and_static_flag_from_archive_fixture(fixture_text):
    viirs = firms.parse_csv(fixture_text("firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv"), "VIIRS_SNPP_SP", "replay")
    static = [d for d in viirs if d.type_code == 2]
    assert static and all(d.static_source and d.confidence_tier == "low" for d in static)
    assert all(d.confidence_tier == "nominal" for d in viirs if d.type_code == 0)  # raw "n"
    modis = firms.parse_csv(fixture_text("firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv"), "MODIS_SP", "replay")
    assert sorted((d.confidence_raw, d.confidence_tier) for d in modis) == [("68", "nominal"), ("82", "high")]


def test_rejects_error_body_and_bad_columns():
    with pytest.raises(firms.FirmsFormatError):
        firms.parse_csv("foo,bar\n1,2\n", "VIIRS_SNPP_NRT", "live")
    with pytest.raises(firms.FirmsFormatError):
        firms._check_body(b"Invalid MAP_KEY.", "VIIRS_SNPP_NRT")
    assert firms.parse_csv("", "VIIRS_SNPP_NRT", "live") == []


def test_day_range_limit():
    with pytest.raises(ValueError):
        firms.area_url("K", "VIIRS_SNPP_SP", (76.0, 9.0, 77.0, 10.0), 6)


def test_fetch_redacts_key_and_caches_with_sha256(tmp_path, monkeypatch, fixture_text):
    body = fixture_text("firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv").encode()
    calls = []

    class Resp:
        content = body

    def fake_request(method, url, **kw):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(firms, "request", fake_request)
    from datetime import date

    args = ("SECRETKEY123", "MODIS_SP", (76.3, 9.9, 76.4, 10.0), 5, date(2023, 2, 27), tmp_path)
    raw1, meta1 = firms.fetch_area(*args)
    raw2, meta2 = firms.fetch_area(*args)
    assert len(calls) == 1 and raw1 == raw2 == body  # second call served from cache
    assert "SECRETKEY123" not in meta1.url_redacted and "{MAP_KEY}" in meta1.url_redacted
    assert meta1.sha256 == meta2.sha256 and meta2.from_cache
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert b"SECRETKEY123" not in p.read_bytes()

"""Regression tests for the issues found in the full code review (each test names the issue)."""

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from conftest import FIXTURES, det
from lfw import firms, incidents, notify
from lfw.agent import fallback
from lfw.agent.contract import validate
from lfw.models import HumanAction, Receptor
from test_contract import make_ctx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


# --- notify: SNS subjects must be ASCII, < 100 characters, one line


def test_sns_subject_is_ascii_and_short():
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    s = notify.subject_for(inc, "Perungudi (OSM: Pallikaranai Dumpyard) — with a very long name " * 3)
    assert s.isascii() and len(s) < 100 and "\n" not in s and s.startswith("[REPLAY] ")


def test_message_leaves_out_hindi_unless_the_draft_had_hindi_enabled():
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    draft = {"draft": {"official_alert_en": "o", "resident_advisory_en": "r", "resident_advisory_hi": "हिंदी"},
             "hindi_enabled": False}
    assert "हिंदी" not in notify.message_for(draft, inc)
    assert "हिंदी" in notify.message_for({**draft, "hindi_enabled": True}, inc)


# --- contract: with Hindi disabled the Hindi field must be empty


def test_hindi_text_with_hindi_disabled_is_rejected():
    ctx = make_ctx(hindi_enabled=False)
    d = fallback.build(ctx).model_dump()
    d["resident_advisory_hi"] = "[REPLAY] संभावित आग"  # unreviewed text: must never be sent
    _, rep = validate(d, ctx)
    c10 = next(c for c in rep.checks if c.check == 10)
    assert c10.passed is False and not rep.passed


def test_check8_error_quotes_the_exact_sentence():
    ctx = make_ctx()
    d = fallback.build(ctx).model_dump()
    d["official_alert_en"] = d["official_alert_en"].replace(ctx.data_age_sentence, "")
    _, rep = validate(d, ctx)
    c8 = next(c for c in rep.checks if c.check == 8)
    assert ctx.data_age_sentence in c8.detail


# --- fallback: always within the contract limits, even with very long receptor names


def test_template_fits_and_validates_with_long_names():
    long_names = [Receptor(receptor_id=f"osm:node/{i}", name=f"Government Higher Secondary School Number {i} "
                           + "Extension Campus " * 6, kind="school", lat=10.0, lon=76.3, distance_km=1 + i / 10)
                  for i in range(40)]
    ctx = make_ctx(receptors_in_zone=long_names, site_receptors=long_names)
    d = fallback.build(ctx)
    assert len(d.official_alert_en) <= 1800 and len(d.resident_advisory_en) <= 700
    assert validate(d.model_dump(), ctx)[1].passed
    assert d.receptor_ids and len(d.receptor_ids) < 8  # fewer receptors listed, still at least one


def test_template_does_not_claim_officials_are_checking():
    assert "Officials are checking" not in fallback.resident_en(make_ctx())


# --- firms: empty key fails clearly; live (undated) calls are never cached


def test_empty_key_fails_clearly_before_any_request(tmp_path):
    with pytest.raises(ValueError, match="MAP_KEY is empty"):
        firms.fetch_area("", "VIIRS_SNPP_NRT", (76.0, 9.0, 77.0, 10.0), 1)


def test_live_calls_are_not_cached(tmp_path, monkeypatch):
    body = (FIXTURES / "firms_live_VIIRS_SNPP_NRT_punjab.csv").read_bytes()
    calls = []

    class Resp:
        content = body

    monkeypatch.setattr(firms, "request", lambda *a, **k: calls.append(1) or Resp())
    for _ in range(2):
        firms.fetch_area("K", "VIIRS_SNPP_NRT", (73.0, 29.0, 77.0, 33.0), 1, cache_dir=tmp_path)
    assert len(calls) == 2 and not any(tmp_path.rglob("*.csv"))


# --- scanner: feeds are skipped (and recorded) once the fetch budget is used up


def test_scan_skips_feeds_after_the_budget(tmp_path):
    from conftest import square_site
    from lfw.models import RawFetch, Site
    from lfw.scanner import run_scan
    from lfw.store import LocalStore

    header = b"latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"

    def fetch(key, src, bbox, day_range, **kw):
        return header, RawFetch(source=src, url_redacted="x", retrieved_utc="t", sha256="s", bytes=len(header))

    site = square_site("s", 10.0, 76.0, 300)
    sites = [Site(site_id="s", name="S", city="C", state="X", polygon_path="-", polygon_source="manual", osm_id=None)]
    rec = run_scan(LocalStore(tmp_path), "K", sites, {"s": site}, datetime(2026, 10, 10, tzinfo=UTC), fetch=fetch,
                   fetch_budget_s=-1)  # budget already used up: every feed is skipped
    assert all("skipped" in v.get("error", "") for v in rec["sources"].values())
    assert LocalStore(tmp_path).latest_scan()["scan_utc"] == "2026-10-10T00:00:00Z"  # record still written


# --- build_sites: a search never replaces a checked outline; curated names are kept


def test_search_result_never_replaces_a_checked_outline():
    import build_sites

    checked = {"osm_id": "way/1+way/2", "verified_by": "someone"}
    assert build_sites.protects_verified(checked, "way/1")
    assert not build_sites.protects_verified(checked, "way/1+way/2")
    assert not build_sites.protects_verified({"osm_id": "way/1", "verified_by": None}, "way/9")


def test_write_site_keeps_curated_name_and_review(tmp_path, monkeypatch):
    import build_sites
    from shapely.geometry import box

    monkeypatch.setattr(build_sites, "SITES_DIR", tmp_path)
    seed = {"site_id": "p", "name": "Seed name", "city": "C"}
    info = {"osm_id": "way/7", "state": "S", "area_ha": 1.0, "osm_name": "x", "tags": {}}
    existing = {"p": {"osm_id": "way/7", "name": "Curated (OSM: x)", "verified_by": "me", "exclusions": ["kiln"]}}
    out: dict = {}
    build_sites.write_site(seed, (info, box(76, 10, 76.01, 10.01)), "t", existing, out)
    assert out["p"]["name"] == "Curated (OSM: x)" and out["p"]["verified_by"] == "me" and out["p"]["exclusions"] == ["kiln"]


def test_overpass_regex_keeps_spaces_and_escapes_metacharacters():
    import build_sites

    assert build_sites.ql_regex("Jawahar Nagar") == "Jawahar Nagar"
    assert build_sites.ql_regex("a.b") == "a\\\\.b"  # \. for the regex, doubled for the QL string
    assert build_sites.ql_regex('x"y') == 'x\\"y'


# --- backtest: unknown --event ids fail; replay keeps a person's review


def test_backtest_unknown_event_fails(monkeypatch, capsys):
    import backtest

    monkeypatch.setattr("sys.argv", ["backtest.py", "--event", "no-such-event"])
    assert backtest.main() == 2 and "unknown event ids" in capsys.readouterr().err


def test_replay_keeps_human_review(tmp_path, monkeypatch):
    import backtest

    viirs = firms.parse_csv((FIXTURES / "firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv").read_text(encoding="utf-8"),
                            "VIIRS_SNPP_SP", "replay")
    modis = firms.parse_csv((FIXTURES / "firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv").read_text(encoding="utf-8"),
                            "MODIS_SP", "replay")
    wind_payload = json.loads((FIXTURES / "openmeteo_archive_brahmapuram_2023-03-02.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(backtest, "fetch_window", lambda *a, **k: (viirs + modis, []))
    monkeypatch.setattr(backtest.wind, "fetch_archive", lambda *a, **k: wind_payload)
    monkeypatch.setenv("STORE", "local")
    monkeypatch.setenv("LOCAL_STORE_DIR", str(tmp_path))
    from lfw.store import LocalStore

    assert backtest.replay("brahmapuram-2023") == 0
    store = LocalStore(tmp_path)
    (inc,) = store.list_incidents("replay")
    reviewed = inc.model_copy(update={"status": "FALSE_ALARM",
                                      "human_action": HumanAction(status="FALSE_ALARM", note="test", utc=datetime.now(UTC))})
    store.put_incident(reviewed)
    assert backtest.replay("brahmapuram-2023") == 0
    assert store.get_incident(inc.incident_id).status == "FALSE_ALARM"


def test_quiet_windows_dates():
    import backtest

    assert backtest.quiet_windows({"reported_start": date(2016, 1, 27)})[0] == (date(2015, 7, 15), date(2015, 8, 13))

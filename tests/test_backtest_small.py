"""Backtest mechanics, offline, on the archive fixtures.

Uses a synthetic test square, not a real site outline, so this test says nothing about whether a
real event is detected (that is the job of `make backtest` after the outlines are verified).
"""

from datetime import date

import pytest
import yaml

import scripts.backtest as bt
from conftest import square_site
from lfw import config, firms


def test_chunks_respect_the_5_day_limit():
    assert bt.chunks(date(2023, 2, 27), date(2023, 3, 14)) == [
        (date(2023, 2, 27), 5), (date(2023, 3, 4), 5), (date(2023, 3, 9), 5), (date(2023, 3, 14), 1)]
    assert sum(n for _, n in bt.chunks(date(2016, 1, 24), date(2016, 2, 3))) == 11


def test_quiet_windows_follow_the_fixed_rule():
    ev = {"reported_start": date(2023, 3, 2)}
    assert bt.quiet_windows(ev) == [(date(2022, 7, 15), date(2022, 8, 13)), (date(2024, 7, 15), date(2024, 8, 13))]
    for a, b in bt.quiet_windows(ev):
        assert (b - a).days + 1 == config.QUIET_WINDOW_DAYS and 7 <= a.month <= b.month <= 9


def _fixture_dets(fixture_text):
    viirs = firms.parse_csv(fixture_text("firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv"), "VIIRS_SNPP_SP", "replay")
    modis = firms.parse_csv(fixture_text("firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv"), "MODIS_SP", "replay")
    return viirs + modis


def test_evaluate_window_is_consistent(fixture_text):
    dets = _fixture_dets(fixture_text)
    lat = sum(d.lat for d in dets) / len(dets)
    lon = sum(d.lon for d in dets) / len(dets)
    site = square_site("test-square", lat, lon, 1000.0)
    res = bt.evaluate_window(site, dets, date(2023, 2, 27), date(2023, 3, 3))
    assert res["raw_in_bbox"] == len(dets)
    assert res["matched"] == sum(res["matched_by_tier"].values()) == len(res["matched_detections"])
    assert res["matched"] + len([n for n in res["nearest_unmatched"]]) <= len(dets)
    assert all(i["incident_id"].startswith("test-square-") for i in res["incidents"])
    assert all(i.mode == "replay" for i in res["_incidents"])
    # Re-running on the same input gives identical output (deterministic, keys stable).
    again = bt.evaluate_window(site, dets + dets, date(2023, 2, 27), date(2023, 3, 3))
    assert again["matched"] == res["matched"] and again["incidents"] == res["incidents"]


def test_window_filter_drops_days_outside(fixture_text):
    dets = _fixture_dets(fixture_text)
    site = square_site("test-square", dets[0].lat, dets[0].lon, 50_000.0)
    res = bt.evaluate_window(site, dets, date(2023, 3, 3), date(2023, 3, 3))
    assert res["raw_in_bbox"] == sum(d.acq_utc.date() == date(2023, 3, 3) for d in dets)


def test_publishable_run_refused_without_verification_or_freeze(monkeypatch, capsys, tmp_path):
    real_sites = bt.load_sites()
    unverified = [s.model_copy(update={"verified_by": None}) for s in real_sites]
    monkeypatch.setattr(bt, "load_sites", lambda: unverified)
    monkeypatch.setattr(bt, "FREEZE", tmp_path / "missing.yaml")
    monkeypatch.setattr("sys.argv", ["backtest.py"])
    assert bt.main() == 2
    err = capsys.readouterr().err
    assert "refusing a publishable run" in err and "no data/config_freeze.yaml" in err


def test_freeze_mismatch_is_detected(monkeypatch, tmp_path):
    f = tmp_path / "freeze.yaml"
    f.write_text("config_hash: not-the-current-hash\n", encoding="utf-8")
    monkeypatch.setattr(bt, "FREEZE", f)
    ok, msg = bt.freeze_state()
    assert not ok and "changed since freeze" in msg


def test_recorded_amendment_is_accepted_but_any_other_change_is_not(monkeypatch):
    ok, msg = bt.freeze_state()  # the real data/config_freeze.yaml
    assert ok and "amended after the freeze: SCAN_DAY_RANGE" in msg
    monkeypatch.setattr(bt.config, "FRP_HIGH_MW", bt.config.FRP_HIGH_MW + 1)
    ok, msg = bt.freeze_state()
    assert not ok and "changed since freeze" in msg


def test_amended_constants_are_live_scan_only():
    frozen = yaml.safe_load(bt.FREEZE.read_text(encoding="utf-8"))
    files = [*(bt.ROOT / "src" / "lfw").rglob("*.py"), *(bt.ROOT / "scripts").glob("*.py")]
    for a in frozen["amendments"]:
        users = {p.name for p in files if a["constant"] in p.read_text(encoding="utf-8")}
        assert users == {"config.py", "scanner.py"}, (a["constant"], users)


@pytest.mark.parametrize("value", [None, 3.2])
def test_fmt(value):
    assert bt.fmt(value) == ("—" if value is None else "3.2")

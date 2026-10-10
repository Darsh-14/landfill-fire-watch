"""Incident grouping and status rules (MVP §6.3)."""

from datetime import UTC, datetime

import pytest

from conftest import det
from lfw import incidents
from lfw.models import HumanAction


def test_gap_over_36_h_splits_incidents():
    dets = [det(t="2023-03-01T10:00"), det(t="2023-03-02T23:01", lat=10.001)]  # 37 h 1 min
    assert len(incidents.build_incidents(dets, "replay")) == 2


def test_gap_of_exactly_36_h_joins():
    dets = [det(t="2023-03-01T10:00"), det(t="2023-03-02T22:00", lat=10.001)]
    (inc,) = incidents.build_incidents(dets, "replay")
    assert len(inc.detection_keys) == 2


def test_two_overpasses_within_24_h_is_probable():
    dets = [det(t="2023-03-02T07:40", source="VIIRS_SNPP_SP"),
            det(t="2023-03-02T19:55", source="VIIRS_SNPP_SP", lat=10.001)]
    (inc,) = incidents.build_incidents(dets, "replay")
    assert inc.status == "PROBABLE" and inc.overpass_count == 2
    assert inc.probable_utc == datetime(2023, 3, 2, 19, 55, tzinfo=UTC)


def test_two_overpasses_more_than_24_h_apart_is_candidate():
    dets = [det(t="2023-03-01T07:40"), det(t="2023-03-02T13:41", lat=10.001)]  # 30 h 1 min
    (inc,) = incidents.build_incidents(dets, "replay")
    assert inc.status == "CANDIDATE"


def test_one_high_detection_with_frp_10_is_probable():
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=10.0)], "replay")
    assert inc.status == "PROBABLE"
    (inc2,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=9.9)], "replay")
    assert inc2.status == "CANDIDATE"


def test_single_low_detection_creates_no_incident():
    assert incidents.build_incidents([det(t="2023-03-02T16:35", tier="low")], "replay") == []


def test_two_low_detections_from_different_overpasses_is_candidate():
    dets = [det(t="2023-03-01T07:40", tier="low"), det(t="2023-03-02T13:41", tier="low", lat=10.001)]
    (inc,) = incidents.build_incidents(dets, "replay")
    assert inc.status == "CANDIDATE"


def test_replay_mode_is_kept_and_mixing_is_rejected():
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    assert inc.mode == "replay" and inc.incident_id == "s1-20230302T1635"
    with pytest.raises(ValueError):
        incidents.build_incidents([det(t="2023-03-02T16:35", mode="live")], "replay")


def test_same_pass_split_across_granules_is_one_overpass():
    a = det(t="2023-03-03T19:36", source="VIIRS_SNPP_SP")
    b = det(t="2023-03-03T19:37", source="VIIRS_SNPP_SP", lat=10.001)
    assert len(set(incidents.overpass_ids([a, b], merge_minutes=10).values())) == 1
    assert len(set(incidents.overpass_ids([a, b], merge_minutes=0).values())) == 2  # literal MVP §5


def test_different_satellites_are_different_overpasses():
    a = det(t="2023-03-02T16:35", source="MODIS_SP", satellite="Terra")
    b = det(t="2023-03-02T16:36", source="MODIS_SP", satellite="Aqua", lat=10.001)
    assert len(set(incidents.overpass_ids([a, b]).values())) == 2


def test_human_review_survives_rebuild():
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    reviewed = inc.model_copy(update={"human_action": HumanAction(
        status="CONFIRMED", note="checked on site", utc=datetime(2023, 3, 3, tzinfo=UTC))})
    (rebuilt,) = incidents.apply_human_actions(
        incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay"),
        {inc.incident_id: reviewed},
    )
    assert rebuilt.status == "CONFIRMED" and rebuilt.human_action.note == "checked on site"

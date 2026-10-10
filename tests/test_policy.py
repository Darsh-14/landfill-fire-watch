"""Cedar approval policy (src/lfw/policies/approve.cedar)."""

import pytest

pytest.importorskip("cedarpy")

from lfw.policy import DUTY_OFFICER, authorize_approve


def ok(**kw):
    args = dict(principal_id="admin-token-holder", roles=[DUTY_OFFICER], incident_id="inc-1",
                mode="replay", draft_validated=True, topic="demo")
    args.update(kw)
    return authorize_approve(**args)[0]


def test_duty_officer_can_send_validated_replay_to_demo():
    assert ok()


def test_live_incident_to_live_topic_allowed():
    assert ok(mode="live", topic="live")


def test_replay_to_live_topic_is_forbidden():
    assert not ok(topic="live")


def test_failed_validator_is_forbidden():
    assert not ok(draft_validated=False)
    assert not ok(mode="live", topic="live", draft_validated=False)


def test_only_duty_officer_may_approve():
    assert not ok(roles=[])
    assert not ok(roles=["viewer"])

"""API routes, approval topic rules, and one offline live scan."""

import json
from datetime import UTC, datetime

import pytest

from conftest import FIXTURES, det, square_site
from handlers import api
from lfw import firms, incidents
from lfw.agent.run import run_draft
from lfw.agent.fake import FakeDrafter
from lfw.agent.tools import build_context
from lfw.models import RawFetch, Site
from lfw.scanner import run_scan
from lfw.store import LocalStore

TOKEN = "test-token-123"
SITE = "brahmapuram-kochi"


class Outbox:
    def __init__(self):
        self.sent = []

    def __call__(self, arn, subject, message):
        self.sent.append((arn, subject, message))
        return f"msg-{len(self.sent)}"


def make_deps(store, outbox):
    return api.Deps(store=store, admin_token=lambda: TOKEN, publish=outbox,
                    start_draft=lambda iid: {"status": "drafting", "incident_id": iid},
                    live_topic_arn="arn:aws:sns:ap-south-1:111111111111:LiveTopic",
                    demo_topic_arn="arn:aws:sns:ap-south-1:111111111111:DemoTopic",
                    backtest=lambda: {"events": []},
                    now=lambda: datetime(2026, 10, 10, 18, 0, tzinfo=UTC))


def seed(store, mode="replay"):
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7, site_id=SITE, mode=mode)], mode)
    store.put_incident(inc)
    return inc


def add_draft(store, inc):
    ctx = build_context(store, inc.incident_id, datetime(2026, 10, 10, tzinfo=UTC))
    rec = run_draft(ctx, FakeDrafter("good"))
    store.put_draft(inc.incident_id, rec["created_utc"], rec)
    return rec


def call(deps, method, path, body=None, token=TOKEN, query=None):
    headers = {"x-admin-token": token} if token else {}
    out = api.route(method, path, {}, query or {}, headers, json.dumps(body) if body is not None else None, deps)
    return out["statusCode"], json.loads(out["body"])


@pytest.fixture
def env(tmp_path):
    store, outbox = LocalStore(tmp_path), Outbox()
    return store, outbox, make_deps(store, outbox)


def test_replay_approval_goes_to_demo_topic_only(env):
    store, outbox, deps = env
    inc = seed(store, "replay")
    add_draft(store, inc)
    code, body = call(deps, "POST", f"/incidents/{inc.incident_id}/approve")
    assert code == 200 and body["topic"] == "demo"
    assert [arn for arn, *_ in outbox.sent] == [deps.demo_topic_arn]
    assert all(deps.live_topic_arn != arn for arn, *_ in outbox.sent)
    assert outbox.sent[0][1].startswith("[REPLAY]")


def test_live_approval_goes_to_live_topic(env):
    store, outbox, deps = env
    inc = seed(store, "live")
    add_draft(store, inc)
    code, body = call(deps, "POST", f"/incidents/{inc.incident_id}/approve")
    assert code == 200 and body["topic"] == "live" and outbox.sent[0][0] == deps.live_topic_arn


def test_replay_never_falls_back_to_live_topic(env):
    store, outbox, deps = env
    deps.demo_topic_arn = ""
    inc = seed(store, "replay")
    add_draft(store, inc)
    code, _ = call(deps, "POST", f"/incidents/{inc.incident_id}/approve")
    assert code == 503 and outbox.sent == []


def test_admin_routes_need_the_token(env):
    store, outbox, deps = env
    inc = seed(store)
    add_draft(store, inc)
    for token in (None, "wrong"):
        for action in ("approve", "draft", "review"):
            code, _ = call(deps, "POST", f"/incidents/{inc.incident_id}/{action}", body={}, token=token)
            assert code == 401
    assert outbox.sent == []


def test_cannot_approve_without_validated_draft_or_twice(env):
    store, outbox, deps = env
    inc = seed(store)
    assert call(deps, "POST", f"/incidents/{inc.incident_id}/approve")[0] == 409
    add_draft(store, inc)
    assert call(deps, "POST", f"/incidents/{inc.incident_id}/approve")[0] == 200
    assert call(deps, "POST", f"/incidents/{inc.incident_id}/approve")[0] == 409
    assert len(outbox.sent) == 1


def test_review_sets_human_status(env):
    store, _, deps = env
    inc = seed(store)
    assert call(deps, "POST", f"/incidents/{inc.incident_id}/review", {"status": "PROBABLE"})[0] == 400
    code, body = call(deps, "POST", f"/incidents/{inc.incident_id}/review", {"status": "FALSE_ALARM", "note": "smoke from kiln"})
    assert code == 200 and body["status"] == "FALSE_ALARM" and store.get_incident(inc.incident_id).human_action.note == "smoke from kiln"


def test_read_routes(env):
    store, _, deps = env
    inc = seed(store)
    store.put_detections([det(t="2023-03-02T16:35", tier="high", frp=22.7, site_id=SITE)])
    store.put_scan({"scan_utc": "2026-10-10T17:00:00Z", "sources": {"VIIRS_SNPP_NRT": {"rows": 5}}, "latest_detection_utc": None})
    code, h = call(deps, "GET", "/health", token=None)
    assert code == 200 and h["minutes_ago"] == 60 and h["sites_monitored"] >= 3
    code, lst = call(deps, "GET", "/incidents", token=None, query={"mode": "replay"})
    assert code == 200 and lst[0]["incident_id"] == inc.incident_id
    code, d = call(deps, "GET", f"/incidents/{inc.incident_id}", token=None)
    assert code == 200 and d["detections"][0]["tier"] == "high" and d["summary"]["mode"] == "replay"
    code, s = call(deps, "GET", "/sites", token=None)
    assert code == 200 and any(x["site_id"] == SITE and x["verified"] for x in s)
    assert call(deps, "GET", "/incidents", token=None, query={"mode": "bogus"})[0] == 400
    assert call(deps, "GET", "/incidents/nope", token=None)[0] == 404
    assert call(deps, "GET", "/backtest", token=None)[0] == 200


def test_draft_route_starts_a_draft(env):
    store, _, deps = env
    inc = seed(store)
    code, body = call(deps, "POST", f"/incidents/{inc.incident_id}/draft", {})
    assert code == 202 and body["status"] == "drafting"


def test_live_scan_offline(tmp_path):
    viirs = (FIXTURES / "firms_live_VIIRS_SNPP_NRT_punjab.csv").read_bytes()
    first = firms.parse_csv(viirs.decode(), "VIIRS_SNPP_NRT", "live")[14]  # a 'h' row in the fixture
    site = square_site("test-site", first.lat, first.lon, 300)
    sites = [Site(site_id="test-site", name="Test", city="X", state="Y", polygon_path="-", polygon_source="manual",
                  osm_id=None)]
    forecast = json.loads((FIXTURES / "openmeteo_forecast_brahmapuram.json").read_text(encoding="utf-8"))

    def fetch(key, src, bbox, day_range, **kw):
        if src == "VIIRS_NOAA21_NRT":
            raise RuntimeError("feed down")
        body = viirs if src == "VIIRS_SNPP_NRT" else viirs.split(b"\n")[0] + b"\n"
        return body, RawFetch(source=src, url_redacted="x", retrieved_utc="t", sha256="s", bytes=len(body))

    store = LocalStore(tmp_path)
    now = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    rec = run_scan(store, "KEY", sites, {"test-site": site}, now, fetch=fetch, forecast=lambda lat, lon: forecast)
    assert "error" in rec["sources"]["VIIRS_NOAA21_NRT"] and rec["sources"]["VIIRS_SNPP_NRT"]["rows"] == 35
    assert rec["matched_detections"] >= 1 and rec["incidents_created"]
    inc = store.get_incident(rec["incidents_created"][0])
    assert inc.mode == "live" and inc.smoke is not None and len(inc.smoke.wind_hours) == 6
    assert store.latest_scan()["scan_utc"] == "2026-10-10T09:00:00Z"
    rec2 = run_scan(store, "KEY", sites, {"test-site": site}, now, fetch=fetch, forecast=lambda lat, lon: forecast)
    assert rec2["incidents_created"] == [] and rec2["incidents_updated"] == rec["incidents_created"]


def test_detail_overpass_groups_match_incident_count(env):
    store, _, deps = env
    dets = [det(t="2023-03-03T19:36", site_id=SITE), det(t="2023-03-03T19:37", site_id=SITE, lat=10.001),
            det(t="2023-03-04T07:40", site_id=SITE, lat=10.002)]
    (inc,) = incidents.build_incidents(dets, "replay")
    store.put_incident(inc)
    store.put_detections(dets)
    _, d = call(deps, "GET", f"/incidents/{inc.incident_id}", token=None)
    assert len({x["overpass"] for x in d["detections"]}) == inc.overpass_count == 2


def test_approve_refused_when_policy_denies(env, monkeypatch):
    store, outbox, deps = env
    inc = seed(store, "replay")
    add_draft(store, inc)
    monkeypatch.setattr(api.policy, "authorize_approve", lambda *a, **k: (False, "cedar: deny"))
    code, body = call(deps, "POST", f"/incidents/{inc.incident_id}/approve")
    assert code == 403 and outbox.sent == []

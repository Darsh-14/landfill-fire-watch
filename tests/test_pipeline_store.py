"""Receptor selection, incident enrichment, and the two store backends."""

import json
from datetime import UTC, datetime

import pytest

from conftest import det, offset_point, square_site
from lfw import incidents, pipeline, receptors
from lfw.models import Receptor, WindHour
from lfw.store import DynamoStore, LocalStore

T = datetime(2023, 3, 2, 16, 0, tzinfo=UTC)


def _receptors(site):
    east = offset_point(site, 5000, 0)
    west = offset_point(site, -5000, 0)
    return [
        Receptor(receptor_id="osm:node/1", name="East School", kind="school", lat=east[0], lon=east[1], distance_km=5.0),
        Receptor(receptor_id="osm:node/2", name=None, kind="hospital", lat=west[0], lon=west[1], distance_km=5.0),
    ]


def test_receptors_in_zone_and_unnamed_display():
    site = square_site("s1", 10.0, 76.0, 400)
    hours = [WindHour(time_utc=T, speed_ms=3.0, from_deg=270)]  # smoke toward east
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    enriched, inside = pipeline.enrich(inc, site, hours, (10.0, 76.0), _receptors(site), T)
    assert [r.receptor_id for r in inside] == ["osm:node/1"] and enriched.receptor_ids == ["osm:node/1"]
    assert enriched.smoke.toward_deg == [90]
    assert receptors.display_name(_receptors(site)[1]) == "Unnamed hospital (OSM)"


def test_no_wind_means_no_zone_and_no_receptors():
    site = square_site("s1", 10.0, 76.0, 400)
    (inc,) = incidents.build_incidents([det(t="2023-03-02T16:35", tier="high", frp=22.7)], "replay")
    enriched, inside = pipeline.enrich(inc, site, [], None, _receptors(site), T)
    assert enriched.smoke is None and inside == [] and enriched.receptor_ids == []


def test_replay_wind_hours_stop_at_status_time():
    d1 = det(t="2023-03-02T16:35", tier="nominal")
    d2 = det(t="2023-03-03T04:50", tier="nominal", lat=10.001)
    d3 = det(t="2023-03-03T20:00", tier="nominal", lat=10.002)
    (inc,) = incidents.build_incidents([d1, d2, d3], "replay")
    assert inc.probable_utc == d2.acq_utc
    hours = [WindHour(time_utc=T.replace(day=dd, hour=h), speed_ms=2, from_deg=90) for dd in (2, 3) for h in range(24)]
    sel = pipeline.wind_hours_for(inc, [d1, d2, d3], hours)
    assert max(h.time_utc for h in sel) == datetime(2023, 3, 3, 10, 0, tzinfo=UTC)  # 04:00 + 6 h; d3 excluded


def _roundtrip(store):
    d = det(t="2023-03-02T16:35", tier="high", frp=22.7)
    (inc,) = incidents.build_incidents([d], "replay")
    store.put_detections([d])
    store.put_incident(inc)
    store.put_scan({"scan_utc": "2026-10-10T12:00:00Z", "n": 1})
    store.put_scan({"scan_utc": "2026-10-10T15:00:00Z", "n": 2})
    store.put_draft(inc.incident_id, "2026-10-10T15:01:00Z", {"v": 1})
    store.put_draft(inc.incident_id, "2026-10-10T15:02:00Z", {"v": 2})
    store.put_approval(inc.incident_id, "2026-10-10T15:03:00Z", {"topic": "demo"})
    assert store.get_incident(inc.incident_id) == inc
    assert [i.incident_id for i in store.list_incidents("replay")] == [inc.incident_id]
    assert store.list_incidents("live") == []
    assert store.get_detections("s1")[0].key == d.key
    assert store.get_detections("s1", since=datetime(2023, 3, 3, tzinfo=UTC)) == []
    assert store.latest_scan()["n"] == 2
    assert store.latest_draft(inc.incident_id) == {"v": 2}
    assert store.list_approvals(inc.incident_id) == [{"topic": "demo"}]
    assert store.get_incident("nope") is None


def test_local_store_roundtrip(tmp_path):
    _roundtrip(LocalStore(tmp_path))


class FakeTable:
    """Just enough of the boto3 Table API for DynamoStore (put/get/query/batch_writer)."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def batch_writer(self, overwrite_by_pkeys=None):
        table = self

        class BW:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def put_item(self, Item):
                table.put_item(Item)

        return BW()

    def query(self, KeyConditionExpression, ScanIndexForward=True, Limit=None, IndexName=None, ExclusiveStartKey=None):
        expr = KeyConditionExpression.get_expression()
        conds = [expr] if expr["operator"] != "AND" else [c.get_expression() for c in expr["values"]]
        def ok(item):
            for c in conds:
                name, *vals = [c["values"][0].name] + list(c["values"][1:])
                v = item.get(name)
                if v is None:
                    return False
                op = c["operator"]
                if op == "=" and v != vals[0]:
                    return False
                if op == "begins_with" and not v.startswith(vals[0]):
                    return False
                if op == "BETWEEN" and not (vals[0] <= v <= vals[1]):
                    return False
            return True
        sort_key = "gsi1sk" if IndexName else "sk"
        rows = sorted((i for i in self.items.values() if ok(i)), key=lambda i: i.get(sort_key, ""),
                      reverse=not ScanIndexForward)
        return {"Items": rows[:Limit] if Limit else rows}


def test_dynamo_store_roundtrip():
    pytest.importorskip("boto3")
    _roundtrip(DynamoStore(table=FakeTable()))


def test_dynamo_keys_follow_mvp_layout():
    pytest.importorskip("boto3")
    t = FakeTable()
    s = DynamoStore(table=t)
    d = det(t="2023-03-02T16:35", tier="high", frp=22.7)
    (inc,) = incidents.build_incidents([d], "replay")
    s.put_detections([d])
    s.put_incident(inc)
    keys = set(t.items)
    assert ("SITE#s1", f"DET#2023-03-02T16:35:00Z#{d.key}") in keys
    assert (f"INC#{inc.incident_id}", "META") in keys
    item = t.items[(f"INC#{inc.incident_id}", "META")]
    assert item["gsi1pk"] == "INCIDENTS#replay" and json.loads(item["data"])["mode"] == "replay"

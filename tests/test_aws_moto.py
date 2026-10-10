"""AWS code paths against moto (validates requests like AWS does, e.g. empty key strings).

Covers: DynamoStore on the template's table + gsi1, raw CSV upload with SHA-256 metadata and checksum,
SSM SecureString secrets, and the API Lambda handler with a real HTTP API v2 event (approve -> SNS).
"""

import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")
from moto import mock_aws  # noqa: E402

from conftest import det  # noqa: E402
from lfw import incidents  # noqa: E402
from lfw.models import RawFetch  # noqa: E402

REGION = "ap-south-1"


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION, "AWS_ACCESS_KEY_ID": "testing",
                 "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SECURITY_TOKEN": "testing", "AWS_SESSION_TOKEN": "testing"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        yield


def make_table():
    """Same key schema and index as template.yaml (Table)."""
    return boto3.resource("dynamodb").create_table(
        TableName="lfw", BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk")],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[{"IndexName": "gsi1", "Projection": {"ProjectionType": "ALL"},
                                 "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"},
                                               {"AttributeName": "gsi1sk", "KeyType": "RANGE"}]}])


def test_dynamo_store_on_real_dynamodb_semantics(aws):
    from lfw.store import DynamoStore

    s = DynamoStore(table=make_table())
    assert s.latest_scan() is None  # empty table, and no empty-string key condition (ValidationException)
    s.put_scan({"scan_utc": "2026-10-10T12:00:00Z", "n": 1})
    s.put_scan({"scan_utc": "2026-10-10T15:00:00Z", "n": 2})
    assert s.latest_scan()["n"] == 2
    d1 = det(t="2023-03-02T16:35", tier="high", frp=22.7)
    d2 = det(t="2023-03-04T01:06", tier="nominal", lat=10.001)
    s.put_detections([d1, d2])
    assert [d.key for d in s.get_detections("s1")] == [d1.key, d2.key]
    assert [d.key for d in s.get_detections("s1", since=datetime(2023, 3, 3, tzinfo=UTC))] == [d2.key]
    (inc,) = incidents.build_incidents([d1, d2], "replay")
    s.put_incident(inc)
    assert s.get_incident(inc.incident_id) == inc
    assert [i.incident_id for i in s.list_incidents("replay")] == [inc.incident_id] and s.list_incidents("live") == []
    s.put_draft(inc.incident_id, "2026-10-10T15:01:00Z", {"v": 1})
    s.put_draft(inc.incident_id, "2026-10-10T15:02:00Z", {"v": 2})
    assert s.latest_draft(inc.incident_id) == {"v": 2}
    s.put_approval(inc.incident_id, "2026-10-10T15:03:00Z", {"topic": "demo"})
    assert s.list_approvals(inc.incident_id) == [{"topic": "demo"}]


def test_raw_csv_upload_has_sha256_metadata_and_checksum(aws, monkeypatch):
    from handlers import scan

    sent = []
    real_client = boto3.client

    def client(name, *a, **k):  # capture the PutObject parameters (moto does not keep S3 checksums)
        c = real_client(name, *a, **k)
        c.meta.events.register("provide-client-params.s3.PutObject", lambda params, **kw: sent.append(dict(params)))
        return c

    monkeypatch.setattr(boto3, "client", client)
    s3 = real_client("s3")
    s3.create_bucket(Bucket="lfw-raw", CreateBucketConfiguration={"LocationConstraint": REGION})
    body = b"latitude,longitude\n10.0,76.0\n"
    sha = hashlib.sha256(body).hexdigest()
    meta = RawFetch(source="VIIRS_SNPP_NRT", url_redacted="https://firms/api/area/csv/{MAP_KEY}/x",
                    retrieved_utc="2026-10-10T12:00:00Z", sha256=sha, bytes=len(body))
    key = scan._s3_put_raw("lfw-raw")("VIIRS_SNPP_NRT", body, meta, datetime(2026, 10, 10, 12, tzinfo=UTC))
    head = s3.head_object(Bucket="lfw-raw", Key=key)
    assert key == "raw/firms/VIIRS_SNPP_NRT/2026/10/10/20261010T120000Z.csv"
    assert head["Metadata"]["sha256"] == sha and head["ContentLength"] == len(body)
    # S3 verifies this header against the body: base64 of the raw SHA-256 digest.
    assert sent[0]["ChecksumSHA256"] == base64.b64encode(hashlib.sha256(body).digest()).decode()


def test_secrets_come_from_ssm_securestring(aws, monkeypatch):
    from lfw import secrets

    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/lfw/firms_map_key", Value="KEY-FROM-SSM", Type="SecureString")
    ssm.put_parameter(Name="/lfw/admin_token", Value="TOKEN-FROM-SSM", Type="SecureString")
    monkeypatch.setenv("FIRMS_KEY_PARAM", "/lfw/firms_map_key")
    monkeypatch.setenv("ADMIN_TOKEN_PARAM", "/lfw/admin_token")
    secrets._cache.clear()
    assert secrets.firms_key() == "KEY-FROM-SSM" and secrets.admin_token() == "TOKEN-FROM-SSM"
    secrets._cache.clear()


def http_event(method, path, *, headers=None, body=None, query=None):
    """An API Gateway HTTP API payload v2.0 event, as Lambda receives it."""
    return {"version": "2.0", "routeKey": f"{method} {path}", "rawPath": path, "rawQueryString": "",
            "headers": headers or {}, "queryStringParameters": query,
            "requestContext": {"http": {"method": method, "path": path}},
            "pathParameters": {"id": path.split("/")[2]} if path.startswith("/incidents/") else None,
            "body": base64.b64encode(json.dumps(body).encode()).decode() if body is not None else None,
            "isBase64Encoded": body is not None}


def test_api_handler_end_to_end_on_aws(aws, monkeypatch):
    from handlers import api
    from lfw import secrets
    from lfw.agent.fake import FakeDrafter
    from lfw.agent.run import run_draft
    from lfw.agent.tools import build_context
    from lfw.store import DynamoStore

    table = make_table()
    ssm, sns = boto3.client("ssm"), boto3.client("sns")
    ssm.put_parameter(Name="/lfw/admin_token", Value="T0K3N", Type="SecureString")
    live = sns.create_topic(Name="LiveTopic")["TopicArn"]
    demo = sns.create_topic(Name="DemoTopic")["TopicArn"]
    for k, v in {"STORE": "dynamodb", "TABLE_NAME": "lfw", "ADMIN_TOKEN_PARAM": "/lfw/admin_token",
                 "LIVE_TOPIC_ARN": live, "DEMO_TOPIC_ARN": demo, "DRAFT_FUNCTION": "lfw-draft"}.items():
        monkeypatch.setenv(k, v)
    secrets._cache.clear()
    monkeypatch.setattr(api, "_deps", None)

    store = DynamoStore(table=table)
    (inc,) = incidents.build_incidents(
        [det(t="2023-03-02T16:35", tier="high", frp=22.7, site_id="brahmapuram-kochi")], "replay")
    store.put_incident(inc)
    rec = run_draft(build_context(store, inc.incident_id), FakeDrafter("good"))
    store.put_draft(inc.incident_id, rec["created_utc"], rec)

    health = api.handler(http_event("GET", "/health"))
    assert health["statusCode"] == 200 and json.loads(health["body"])["last_scan_utc"] is None
    lst = api.handler(http_event("GET", "/incidents", query={"mode": "replay"}))
    assert [i["incident_id"] for i in json.loads(lst["body"])] == [inc.incident_id]
    assert api.handler(http_event("POST", f"/incidents/{inc.incident_id}/approve"))["statusCode"] == 401
    ok = api.handler(http_event("POST", f"/incidents/{inc.incident_id}/approve", headers={"x-admin-token": "T0K3N"}))
    body = json.loads(ok["body"])
    assert ok["statusCode"] == 200 and body["topic"] == "demo" and body["message_id"]
    review = api.handler(http_event("POST", f"/incidents/{inc.incident_id}/review",
                                    headers={"x-admin-token": "T0K3N"}, body={"status": "CONFIRMED", "note": "seen"}))
    assert review["statusCode"] == 200 and store.get_incident(inc.incident_id).status == "CONFIRMED"
    secrets._cache.clear()


def test_api_handler_returns_json_500_on_unexpected_error(aws, monkeypatch, capsys):
    from handlers import api

    class Broken:
        def latest_scan(self):
            raise RuntimeError("table gone")

    deps = api.Deps(store=Broken(), admin_token=lambda: "t", publish=lambda *a: "m", start_draft=lambda i: {},
                    live_topic_arn="", demo_topic_arn="", backtest=lambda: None)
    monkeypatch.setattr(api, "_deps", deps)
    out = api.handler(http_event("GET", "/health"))
    assert out["statusCode"] == 500 and "internal error" in json.loads(out["body"])["error"]
    assert "table gone" in capsys.readouterr().out  # the cause is in the logs

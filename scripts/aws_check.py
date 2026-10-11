"""Post-deploy verification for local/aws-evidence.md (kept out of the repo) (prompt §7 checklist).

Steps (each prints OK/FAIL with the evidence):
  1. invoke ScanFunction once (synchronously) and show its result
  2. read the newest SCAN record from DynamoDB
  3. list the newest raw FIRMS CSV in S3 with its SHA-256 metadata
  4. GET /health and /incidents on the HTTP API
  5. (--draft) POST /incidents/<replay id>/draft (Bedrock) and wait for the validated draft
  6. (--approve) POST /approve: sends the [REPLAY] email via the DEMO topic. Check your inbox.
  7. show the EventBridge Scheduler schedule targeting ScanFunction
Admin token is read from SSM /lfw/admin_token and never printed.

Usage: python scripts/aws_check.py [--draft] [--approve] [--incident ID]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aws_common import session, stack_outputs

REPLAY_ID = "brahmapuram-kochi-20230302T1635"


def ok(step: str, good: bool, detail: str = "") -> bool:
    print(f"[{'OK' if good else 'FAIL'}] {step}" + (f"\n      {detail}" if detail else ""))
    return good


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--incident", default=REPLAY_ID)
    args = ap.parse_args()
    s = session()
    out = stack_outputs()
    results = {}

    from botocore.config import Config

    # The scan may run up to its 300 s timeout; no client retries (a retry would start a second scan).
    lam = s.client("lambda", config=Config(read_timeout=320, retries={"max_attempts": 1}))
    r = lam.invoke(FunctionName=out["ScanFunctionName"], InvocationType="RequestResponse", Payload=b'{"source": "aws_check"}')
    payload = json.loads(r["Payload"].read() or b"{}")
    results["scan"] = ok("1 ScanFunction invoked", "FunctionError" not in r, json.dumps(payload)[:300])

    from boto3.dynamodb.conditions import Key

    table = s.resource("dynamodb").Table(out["TableName"])
    items = table.query(KeyConditionExpression=Key("pk").eq("SCAN"), ScanIndexForward=False, Limit=1)["Items"]
    rec = json.loads(items[0]["data"]) if items else {}
    results["ddb"] = ok("2 DynamoDB scan record (pk=SCAN)", bool(items),
                        f"sk={items[0]['sk'] if items else None} raw={rec.get('raw_detections')} matched={rec.get('matched_detections')}")

    s3 = s.client("s3")
    objs = s3.list_objects_v2(Bucket=out["BucketName"], Prefix="raw/firms/").get("Contents", [])
    newest = max(objs, key=lambda o: o["LastModified"]) if objs else None
    meta = s3.head_object(Bucket=out["BucketName"], Key=newest["Key"])["Metadata"] if newest else {}
    results["s3"] = ok("3 S3 raw FIRMS CSV with SHA-256 metadata", bool(meta.get("sha256")),
                       f"s3://{out['BucketName']}/{newest['Key'] if newest else '-'} sha256={meta.get('sha256')}")

    api = out["ApiUrl"].rstrip("/")
    h = httpx.get(f"{api}/health", timeout=30)
    inc = httpx.get(f"{api}/incidents", timeout=30)
    results["api"] = ok("4 GET /health and /incidents", h.status_code == 200 and inc.status_code == 200,
                        f"health={h.text[:200]} | incidents={len(inc.json()) if inc.status_code == 200 else inc.text[:100]}")

    token = None
    if args.draft or args.approve:
        token = s.client("ssm").get_parameter(Name="/lfw/admin_token", WithDecryption=True)["Parameter"]["Value"]
    if args.draft:
        before = httpx.get(f"{api}/incidents/{args.incident}", timeout=30).json().get("draft")
        r = httpx.post(f"{api}/incidents/{args.incident}/draft", headers={"x-admin-token": token}, timeout=30)
        draft = None
        for _ in range(40):
            time.sleep(3)
            d = httpx.get(f"{api}/incidents/{args.incident}", timeout=30).json().get("draft")
            if d and (not before or d["created_utc"] != before["created_utc"]):
                draft = d
                break
        results["draft"] = ok("5 Bedrock draft (DraftFunction)", bool(draft and draft["validated"]),
                              f"POST {r.status_code}; model={draft and draft['model']} template_used={draft and draft['template_used']} "
                              f"attempts={draft and [(a['source'], a['passed']) for a in draft['attempts']]}")
    if args.approve:
        r = httpx.post(f"{api}/incidents/{args.incident}/approve", headers={"x-admin-token": token}, timeout=30)
        results["approve"] = ok("6 Approve -> SNS", r.status_code == 200 and r.json().get("topic") == "demo",
                                f"{r.status_code} {r.text[:200]}  (now check the inbox for the [REPLAY] email)")

    sched = s.client("scheduler")
    found = None
    for page in sched.get_paginator("list_schedules").paginate():
        for sc in page["Schedules"]:
            detail = sched.get_schedule(Name=sc["Name"], GroupName=sc.get("GroupName", "default"))
            if out["ScanFunctionName"] in detail["Target"]["Arn"]:
                found = detail
    results["schedule"] = ok("7 EventBridge Scheduler schedule", bool(found),
                             f"{found['Name']} {found['ScheduleExpression']} {found['State']}" if found else "")
    print("\nSummary:", ", ".join(f"{k}={'ready' if v else 'NOT ready'}" for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

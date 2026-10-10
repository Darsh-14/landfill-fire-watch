"""ApiFunction: HTTP API routes (MVP §8). Admin routes need header x-admin-token.

The admin token is a demo control, not production authentication (README says so).
`route()` holds all logic with injected dependencies; `handler()` wires AWS; scripts/local_api.py
wires the local store, a local outbox instead of SNS, and synchronous drafting.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from lfw import incidents, notify, policy
from lfw import receptors as rc
from lfw.logjson import log_json
from lfw.models import HumanAction
from lfw.paths import ROOT
from lfw.sites import load_sites
from lfw.store import Store
from lfw.timeutil import ist_str, utc_iso

REVIEW_STATUSES = {"CONFIRMED", "FALSE_ALARM", "CLOSED"}
SOURCES_LABEL = "VIIRS S-NPP, NOAA-20, NOAA-21, MODIS"


@dataclass
class Deps:
    store: Store
    admin_token: Callable[[], str]
    publish: Callable[[str, str, str], str]  # (topic_arn, subject, message) -> message id
    start_draft: Callable[[str], dict]  # incident_id -> response body (async in AWS, sync locally)
    live_topic_arn: str
    demo_topic_arn: str
    backtest: Callable[[], dict | None]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


def resp(status: int, body: Any) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _authorised(headers: dict, deps: Deps) -> bool:
    expected = deps.admin_token()
    got = {k.lower(): v for k, v in (headers or {}).items()}.get("x-admin-token", "")
    return bool(expected) and hmac.compare_digest(got.encode(), expected.encode())


def _site_index() -> dict:
    return {s.site_id: s for s in load_sites()}


def health(deps: Deps) -> dict:
    scan = deps.store.latest_scan()
    now = deps.now()
    out = {"status": "ok", "sources": SOURCES_LABEL, "sites_monitored": len(load_sites()), "last_scan_utc": None}
    if scan:
        t = datetime.fromisoformat(scan["scan_utc"].replace("Z", "+00:00"))
        out.update(last_scan_utc=scan["scan_utc"], last_scan_ist=ist_str(t),
                   minutes_ago=int((now - t).total_seconds() // 60),
                   latest_detection_utc=scan.get("latest_detection_utc"),
                   source_status={k: ("error" if "error" in v else v.get("rows")) for k, v in scan["sources"].items()})
    return out


def sites(deps: Deps) -> list[dict]:
    out = []
    since = deps.now() - timedelta(days=30)
    for s in load_sites():
        fc = json.loads((ROOT / s.polygon_path).read_text(encoding="utf-8"))
        dets = deps.store.get_detections(s.site_id, since=since)
        out.append({"site_id": s.site_id, "name": s.name, "city": s.city, "state": s.state,
                    "verified": bool(s.verified_by), "verified_by": s.verified_by, "exclusions": s.exclusions,
                    "outline": fc, "last_detection_utc": utc_iso(dets[-1].acq_utc) if dets else None})
    return out


def incident_summary(inc) -> dict:
    return {"incident_id": inc.incident_id, "site_id": inc.site_id, "mode": inc.mode, "status": inc.status,
            "first_utc": utc_iso(inc.first_utc), "first_ist": ist_str(inc.first_utc),
            "last_ist": ist_str(inc.last_utc), "overpass_count": inc.overpass_count,
            "max_frp_mw": inc.max_frp_mw, "receptors_in_zone": len(inc.receptor_ids),
            "human_status": inc.human_action.status if inc.human_action else None}


def incident_detail(deps: Deps, incident_id: str) -> dict | None:
    inc = deps.store.get_incident(incident_id)
    if inc is None:
        return None
    keys = set(inc.detection_keys)
    dets = [d for d in deps.store.get_detections(inc.site_id) if d.key in keys]
    ov = incidents.overpass_ids(dets)  # same grouping the status rules use
    by_id = {r.receptor_id: r for r in rc.load_receptors(inc.site_id)}
    recs = [by_id[i] for i in inc.receptor_ids if i in by_id]
    site = _site_index().get(inc.site_id)
    return {
        "incident": inc.model_dump(mode="json"),
        "summary": incident_summary(inc),
        "site": {"name": site.name, "city": site.city, "state": site.state} if site else None,
        "detections": [{"key": d.key, "lat": d.lat, "lon": d.lon, "acq_utc": utc_iso(d.acq_utc),
                        "acq_ist": ist_str(d.acq_utc), "source": d.source, "satellite": d.satellite,
                        "tier": d.confidence_tier, "frp_mw": d.frp_mw, "scan_km": d.scan_km,
                        "track_km": d.track_km, "static": d.static_source, "match_distance_m": d.match_distance_m,
                        "overpass": f"{ov[d.key][0]}|{ov[d.key][1]}|{utc_iso(ov[d.key][2])}",
                        "overpass_ist": ist_str(ov[d.key][2])}
                       for d in dets],
        "receptors": [{"receptor_id": r.receptor_id, "name": rc.display_name(r), "kind": r.kind,
                       "distance_km": r.distance_km, "lat": r.lat, "lon": r.lon}
                      for r in sorted(recs, key=lambda r: r.distance_km)],
        "draft": deps.store.latest_draft(incident_id),
        "approvals": deps.store.list_approvals(incident_id),
    }


def approve(deps: Deps, incident_id: str) -> dict:
    inc = deps.store.get_incident(incident_id)
    if inc is None:
        return resp(404, {"error": "unknown incident"})
    draft = deps.store.latest_draft(incident_id)
    if not draft or not draft.get("validated"):
        return resp(409, {"error": "no validated draft to approve"})
    if any(a.get("draft_created_utc") == draft["created_utc"] for a in deps.store.list_approvals(incident_id)):
        return resp(409, {"error": "this draft was already approved and sent"})
    try:
        kind, arn = notify.topic_for(inc.mode, deps.live_topic_arn, deps.demo_topic_arn)
    except notify.TopicError as exc:
        return resp(503, {"error": str(exc)})
    # Second gate: the Cedar approval policy (duty officer only; replay -> demo only; validated drafts only).
    allowed, why = policy.authorize_approve("admin-token-holder", [policy.DUTY_OFFICER], incident_id,
                                            inc.mode, bool(draft.get("validated")), kind)
    if not allowed:
        log_json("approval_refused", incident_id=incident_id, reason=why)
        return resp(403, {"error": "approval refused by policy", "detail": why})
    site = _site_index().get(inc.site_id)
    msg_id = deps.publish(arn, notify.subject_for(inc, site.name if site else inc.site_id), notify.message_for(draft, inc))
    now = utc_iso(deps.now())
    rec = {"approved_utc": now, "topic": kind, "message_id": msg_id, "draft_created_utc": draft["created_utc"],
           "template_used": draft.get("template_used"), "mode": inc.mode}
    deps.store.put_approval(incident_id, now, rec)
    log_json("approval_sent", incident_id=incident_id, topic=kind, mode=inc.mode, message_id=msg_id)
    return resp(200, rec)


def review(deps: Deps, incident_id: str, body: dict) -> dict:
    inc = deps.store.get_incident(incident_id)
    if inc is None:
        return resp(404, {"error": "unknown incident"})
    status = (body or {}).get("status")
    if status not in REVIEW_STATUSES:
        return resp(400, {"error": f"status must be one of {sorted(REVIEW_STATUSES)}"})
    action = HumanAction(status=status, note=str((body or {}).get("note", ""))[:500], utc=deps.now())
    inc = inc.model_copy(update={"human_action": action, "status": status})
    deps.store.put_incident(inc)
    log_json("incident_reviewed", incident_id=incident_id, status=status)
    return resp(200, incident_summary(inc))


def route(method: str, path: str, path_params: dict, query: dict, headers: dict, body: str | None, deps: Deps) -> dict:
    method = method.upper()
    parts = [p for p in path.split("/") if p]
    iid = (path_params or {}).get("id") or (parts[1] if len(parts) >= 2 and parts[0] == "incidents" else None)
    if method == "GET" and parts == ["health"]:
        return resp(200, health(deps))
    if method == "GET" and parts == ["sites"]:
        return resp(200, sites(deps))
    if method == "GET" and parts == ["incidents"]:
        mode = (query or {}).get("mode")
        if mode not in (None, "live", "replay"):
            return resp(400, {"error": "mode must be live or replay"})
        incs = deps.store.list_incidents(mode)
        incs.sort(key=lambda i: (i.mode != "live", -i.first_utc.timestamp()))  # live first, newest first
        return resp(200, [incident_summary(i) for i in incs])
    if method == "GET" and parts == ["backtest"]:
        bt = deps.backtest()
        return resp(200, bt) if bt else resp(404, {"error": "no backtest published"})
    if method == "GET" and len(parts) == 2 and parts[0] == "incidents":
        detail = incident_detail(deps, iid)
        return resp(200, detail) if detail else resp(404, {"error": "unknown incident"})
    if method == "POST" and len(parts) == 3 and parts[0] == "incidents":
        if not _authorised(headers, deps):
            return resp(401, {"error": "admin token required (header x-admin-token)"})
        action = parts[2]
        if action == "draft":
            if deps.store.get_incident(iid) is None:
                return resp(404, {"error": "unknown incident"})
            return resp(202, deps.start_draft(iid))
        if action == "approve":
            return approve(deps, iid)
        if action == "review":
            try:
                data = json.loads(body or "{}")
            except json.JSONDecodeError:
                return resp(400, {"error": "body must be JSON"})
            return review(deps, iid, data)
    return resp(404, {"error": f"no route {method} {path}"})


# ---------------------------------------------------------------- AWS wiring

_deps: Deps | None = None


def _aws_deps() -> Deps:
    import boto3

    from lfw import secrets
    from lfw.store import get_store

    sns = boto3.client("sns")
    lam = boto3.client("lambda")
    s3 = boto3.client("s3")
    draft_fn = os.environ["DRAFT_FUNCTION"]
    bucket = os.environ.get("RAW_BUCKET")

    def start_draft(incident_id: str) -> dict:
        lam.invoke(FunctionName=draft_fn, InvocationType="Event", Payload=json.dumps({"incident_id": incident_id}).encode())
        log_json("draft_requested", incident_id=incident_id)
        return {"status": "drafting", "incident_id": incident_id, "poll": f"/incidents/{incident_id}"}

    def backtest() -> dict | None:
        if bucket:
            try:
                return json.loads(s3.get_object(Bucket=bucket, Key="backtest/backtest.json")["Body"].read())
            except Exception:  # fall back to the copy bundled at package time
                pass
        path = ROOT / "data" / "backtest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    return Deps(
        store=get_store(), admin_token=secrets.admin_token,
        publish=lambda arn, subject, message: notify.publish(sns, arn, subject, message),
        start_draft=start_draft, live_topic_arn=os.environ.get("LIVE_TOPIC_ARN", ""),
        demo_topic_arn=os.environ.get("DEMO_TOPIC_ARN", ""), backtest=backtest,
    )


def handler(event, context=None) -> dict:
    global _deps
    if _deps is None:
        _deps = _aws_deps()
    http = event.get("requestContext", {}).get("http", {})
    body = event.get("body")
    if body and event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    try:
        out = route(http.get("method", "GET"), event.get("rawPath", "/"), event.get("pathParameters") or {},
                    event.get("queryStringParameters") or {}, event.get("headers") or {}, body, _deps)
    except Exception as exc:  # log the cause (no headers, no secrets) and return JSON instead of a bare 500
        log_json("api_error", method=http.get("method"), path=event.get("rawPath"),
                 error=f"{type(exc).__name__}: {exc}"[:300])
        out = resp(500, {"error": "internal error; see the ApiFunction logs"})
    log_json("api_request", method=http.get("method"), path=event.get("rawPath"), status=out["statusCode"])
    return out

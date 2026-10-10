"""Storage with one interface and two backends (CLAUDE.md §8): `local` (JSON in out/store/) and
`dynamodb` (single table, MVP §5 keys). Select with env var STORE.

DynamoDB layout (pk / sk), bodies stored as a JSON string attribute `data`:
  Scan record   SCAN               / {utc_iso}
  Detection     SITE#{site_id}     / DET#{acq_utc}#{key}
  Incident      INC#{incident_id}  / META        (+ gsi1pk INCIDENTS#{mode}, gsi1sk {first_utc})
  Draft         INC#{incident_id}  / DRAFT#{utc_iso}
  Approval      INC#{incident_id}  / APPROVAL#{utc_iso}
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

from lfw.models import Detection, Incident

from lfw.paths import ROOT


class Store(Protocol):
    def put_scan(self, rec: dict) -> None: ...
    def latest_scan(self) -> dict | None: ...
    def put_detections(self, dets: list[Detection]) -> None: ...
    def get_detections(self, site_id: str, since: datetime | None = None) -> list[Detection]: ...
    def put_incident(self, inc: Incident) -> None: ...
    def get_incident(self, incident_id: str) -> Incident | None: ...
    def list_incidents(self, mode: str | None = None) -> list[Incident]: ...
    def put_draft(self, incident_id: str, utc_iso: str, draft: dict) -> None: ...
    def latest_draft(self, incident_id: str) -> dict | None: ...
    def put_approval(self, incident_id: str, utc_iso: str, rec: dict) -> None: ...
    def list_approvals(self, incident_id: str) -> list[dict]: ...


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LocalStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ROOT / "out" / "store"

    def _read(self, path: Path, default):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def _write(self, path: Path, obj) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
        tmp.replace(path)

    def put_scan(self, rec: dict) -> None:
        self._write(self.root / "scans" / f"{rec['scan_utc'].replace(':', '')}.json", rec)

    def latest_scan(self) -> dict | None:
        files = sorted((self.root / "scans").glob("*.json"))
        return self._read(files[-1], None) if files else None

    def put_detections(self, dets: list[Detection]) -> None:
        by_site: dict[str, list[Detection]] = {}
        for d in dets:
            by_site.setdefault(d.site_id or "_unmatched", []).append(d)
        for site, group in by_site.items():
            path = self.root / "detections" / f"{site}.json"
            cur = self._read(path, {})
            cur.update({d.key: d.model_dump(mode="json") for d in group})
            self._write(path, cur)

    def get_detections(self, site_id: str, since: datetime | None = None) -> list[Detection]:
        cur = self._read(self.root / "detections" / f"{site_id}.json", {})
        dets = [Detection(**v) for v in cur.values()]
        if since is not None:
            dets = [d for d in dets if d.acq_utc >= since]
        return sorted(dets, key=lambda d: (d.acq_utc, d.key))

    def put_incident(self, inc: Incident) -> None:
        self._write(self.root / "incidents" / f"{inc.incident_id}.json", inc.model_dump(mode="json"))

    def get_incident(self, incident_id: str) -> Incident | None:
        raw = self._read(self.root / "incidents" / f"{incident_id}.json", None)
        return Incident(**raw) if raw else None

    def list_incidents(self, mode: str | None = None) -> list[Incident]:
        incs = [Incident(**self._read(p, {})) for p in sorted((self.root / "incidents").glob("*.json"))]
        return [i for i in incs if mode is None or i.mode == mode]

    def put_draft(self, incident_id: str, utc_iso: str, draft: dict) -> None:
        self._write(self.root / "drafts" / incident_id / f"{utc_iso.replace(':', '')}.json", draft)

    def latest_draft(self, incident_id: str) -> dict | None:
        files = sorted((self.root / "drafts" / incident_id).glob("*.json"))
        return self._read(files[-1], None) if files else None

    def put_approval(self, incident_id: str, utc_iso: str, rec: dict) -> None:
        self._write(self.root / "approvals" / incident_id / f"{utc_iso.replace(':', '')}.json", rec)

    def list_approvals(self, incident_id: str) -> list[dict]:
        return [self._read(p, {}) for p in sorted((self.root / "approvals" / incident_id).glob("*.json"))]


class DynamoStore:
    def __init__(self, table=None, table_name: str | None = None) -> None:
        if table is None:
            import boto3  # in the Lambda runtime; local dev installs it with the dev extra

            table = boto3.resource("dynamodb").Table(table_name or os.environ["TABLE_NAME"])
        self.t = table

    def _put(self, pk: str, sk: str, body, **extra) -> None:
        self.t.put_item(Item={"pk": pk, "sk": sk, "data": json.dumps(body, default=str, ensure_ascii=False), **extra})

    def _query(self, pk: str, prefix: str, *, newest_first: bool = False, limit: int | None = None,
               start: str | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        # DynamoDB rejects an empty string in a key condition, so "no prefix" means "pk only".
        cond = Key("pk").eq(pk)
        if start:
            cond = cond & Key("sk").between(start, prefix + "~")
        elif prefix:
            cond = cond & Key("sk").begins_with(prefix)
        kw = {"KeyConditionExpression": cond, "ScanIndexForward": not newest_first}
        if limit:
            kw["Limit"] = limit
        items, resp = [], self.t.query(**kw)
        items += resp.get("Items", [])
        while "LastEvaluatedKey" in resp and not (limit and len(items) >= limit):
            resp = self.t.query(**kw, ExclusiveStartKey=resp["LastEvaluatedKey"])
            items += resp.get("Items", [])
        return [json.loads(i["data"]) for i in items]

    def put_scan(self, rec: dict) -> None:
        self._put("SCAN", rec["scan_utc"], rec)

    def latest_scan(self) -> dict | None:
        rows = self._query("SCAN", "", newest_first=True, limit=1)
        return rows[0] if rows else None

    def put_detections(self, dets: list[Detection]) -> None:
        with self.t.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as bw:
            for d in dets:
                bw.put_item(Item={"pk": f"SITE#{d.site_id}", "sk": f"DET#{_iso(d.acq_utc)}#{d.key}",
                                  "data": d.model_dump_json()})

    def get_detections(self, site_id: str, since: datetime | None = None) -> list[Detection]:
        start = f"DET#{_iso(since)}" if since else None
        return [Detection(**r) for r in self._query(f"SITE#{site_id}", "DET#", start=start)]

    def put_incident(self, inc: Incident) -> None:
        self._put(f"INC#{inc.incident_id}", "META", inc.model_dump(mode="json"),
                  gsi1pk=f"INCIDENTS#{inc.mode}", gsi1sk=_iso(inc.first_utc))

    def get_incident(self, incident_id: str) -> Incident | None:
        item = self.t.get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item")
        return Incident(**json.loads(item["data"])) if item else None

    def list_incidents(self, mode: str | None = None) -> list[Incident]:
        from boto3.dynamodb.conditions import Key

        out = []
        for m in ([mode] if mode else ["live", "replay"]):
            kw = {"IndexName": "gsi1", "KeyConditionExpression": Key("gsi1pk").eq(f"INCIDENTS#{m}"),
                  "ScanIndexForward": False}
            resp = self.t.query(**kw)
            items = resp.get("Items", [])
            while "LastEvaluatedKey" in resp:
                resp = self.t.query(**kw, ExclusiveStartKey=resp["LastEvaluatedKey"])
                items += resp.get("Items", [])
            out += [Incident(**json.loads(i["data"])) for i in items]
        return out

    def put_draft(self, incident_id: str, utc_iso: str, draft: dict) -> None:
        self._put(f"INC#{incident_id}", f"DRAFT#{utc_iso}", draft)

    def latest_draft(self, incident_id: str) -> dict | None:
        rows = self._query(f"INC#{incident_id}", "DRAFT#", newest_first=True, limit=1)
        return rows[0] if rows else None

    def put_approval(self, incident_id: str, utc_iso: str, rec: dict) -> None:
        self._put(f"INC#{incident_id}", f"APPROVAL#{utc_iso}", rec)

    def list_approvals(self, incident_id: str) -> list[dict]:
        return self._query(f"INC#{incident_id}", "APPROVAL#")


def get_store() -> Store:
    kind = os.environ.get("STORE", "local")
    if kind == "dynamodb":
        return DynamoStore()
    if kind == "local":
        return LocalStore(Path(os.environ["LOCAL_STORE_DIR"]) if os.environ.get("LOCAL_STORE_DIR") else None)
    raise ValueError(f"unknown STORE={kind!r}")

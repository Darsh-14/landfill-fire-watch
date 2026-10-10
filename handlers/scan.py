"""ScanFunction: EventBridge Scheduler rate(3 hours) -> one live scan (MVP §3, §12).

Locally: `make scan-local` (STORE=local, raw CSVs to cache/raw/, FIRMS key from .env).
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from lfw import secrets
from lfw.logjson import log_json
from lfw.models import RawFetch
from lfw.scanner import run_scan
from lfw.sites import load_shapes, load_sites
from lfw.store import get_store


def _s3_put_raw(bucket: str):
    import boto3

    s3 = boto3.client("s3")

    def put(src: str, body: bytes, meta: RawFetch, now: datetime) -> str:
        key = f"raw/firms/{src}/{now:%Y/%m/%d}/{now:%Y%m%dT%H%M%SZ}.csv"
        s3.put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="text/csv",
            ChecksumSHA256=base64.b64encode(hashlib.sha256(body).digest()).decode(),
            Metadata={"sha256": meta.sha256, "source": src, "retrieved-utc": meta.retrieved_utc,
                      "url": meta.url_redacted},
        )
        return key

    return put


def _local_put_raw(root: Path):
    def put(src: str, body: bytes, meta: RawFetch, now: datetime) -> str:
        path = root / src / f"{now:%Y%m%dT%H%M%SZ}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        path.with_suffix(".json").write_text(meta.model_dump_json(indent=1), encoding="utf-8", newline="\n")
        return str(path)

    return put


def handler(event=None, context=None) -> dict:
    now = datetime.now(UTC)
    key = secrets.firms_key()
    if not key:
        log_json("scan_error", error="FIRMS key missing")
        raise RuntimeError("FIRMS key missing")
    sites = load_sites()
    shapes = load_shapes(sites)
    bucket = os.environ.get("RAW_BUCKET")
    put_raw = _s3_put_raw(bucket) if bucket else _local_put_raw(Path("cache/raw"))
    log_json("scan_start", trigger=(event or {}).get("source", "manual"), sites=len(sites))
    rec = run_scan(get_store(), key, sites, shapes, now, put_raw=put_raw)
    return {"scan_utc": rec["scan_utc"], "matched": rec["matched_detections"],
            "created": rec["incidents_created"], "updated": rec["incidents_updated"]}


if __name__ == "__main__":
    print(handler({"source": "scan-local"}))

"""One live scan (MVP §3): FIRMS NRT for India -> raw CSV archive -> match -> incidents -> smoke ->
receptors -> store. Dependencies are injected so the same code runs in Lambda, locally and in tests.

No SNS here: a scan never sends anything (CLAUDE.md rule 4). It only updates incidents for review.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from lfw import detect, firms, incidents, pipeline, wind
from lfw import receptors as rc
from lfw.config import INDIA_BBOX, LIVE_SOURCES, SCAN_DAY_RANGE, config_hash
from lfw.geo import SiteShape
from lfw.logjson import log_json
from lfw.models import Detection, RawFetch, Site
from lfw.store import Store
from lfw.timeutil import utc_iso

FetchFn = Callable[..., tuple[bytes, RawFetch]]
PutRawFn = Callable[[str, bytes, RawFetch, datetime], str]


def run_scan(
    store: Store,
    key: str,
    sites: list[Site],
    shapes: dict[str, SiteShape],
    now: datetime,
    *,
    fetch: FetchFn = firms.fetch_area,
    put_raw: PutRawFn | None = None,
    forecast: Callable[[float, float], dict] = wind.fetch_forecast,
    lookback_days: int = 7,
    fetch_budget_s: float | None = None,
    fetch_timeout_s: float = 60.0,
    fetch_retries: int | None = None,
) -> dict:
    """With fetch_budget_s (Lambda), feeds not started within the budget are skipped and recorded,
    so the scan record is always written before the function times out."""
    t0 = time.monotonic()
    sources: dict[str, dict] = {}
    all_dets: list[Detection] = []
    for src in LIVE_SOURCES:
        info: dict = {}
        if fetch_budget_s is not None and time.monotonic() - t0 > fetch_budget_s:
            info["error"] = f"skipped: fetch time budget of {fetch_budget_s:.0f} s used up"
            sources[src] = info
            log_json("scan_source", source=src, **info)
            continue
        try:
            kw = {"timeout": fetch_timeout_s} | ({} if fetch_retries is None else {"retries": fetch_retries})
            body, meta = fetch(key, src, INDIA_BBOX, SCAN_DAY_RANGE, **kw)
            info.update(rows=0, sha256=meta.sha256, bytes=meta.bytes, retrieved_utc=meta.retrieved_utc)
            if put_raw is not None:
                info["s3_key"] = put_raw(src, body, meta, now)
            dets = firms.parse_csv(body.decode("utf-8"), src, "live")
            info["rows"] = len(dets)
            info["latest_acq_utc"] = utc_iso(max(d.acq_utc for d in dets)) if dets else None
            all_dets += dets
        except Exception as exc:  # one failing feed must not stop the others; errors are redacted
            info["error"] = f"{type(exc).__name__}: {exc}"[:300]
        sources[src] = info
        log_json("scan_source", source=src, **{k: v for k, v in info.items() if k != "sha256"})

    matched = detect.match(all_dets, shapes)
    if matched:
        store.put_detections(matched)
    log_json("scan_matched", raw=len(all_dets), matched=len(matched),
             sites=sorted({d.site_id for d in matched if d.site_id}))

    since = now - timedelta(days=lookback_days)
    live_existing = {i.incident_id: i for i in store.list_incidents("live")}
    touched = {d.site_id for d in matched if d.site_id}
    touched |= {i.site_id for i in live_existing.values() if i.last_utc >= since}
    updated, created = [], []
    for site_id in sorted(touched):
        # Reach back to the first detection of any still-open incident, so a fire longer than the
        # lookback keeps its incident id (and its review) instead of being split into a new one.
        open_firsts = [i.first_utc for i in live_existing.values() if i.site_id == site_id and i.last_utc >= since]
        site_since = min([since, *open_firsts])
        recent = [d for d in store.get_detections(site_id, since=site_since) if d.mode == "live"]
        rebuilt = incidents.apply_human_actions(incidents.build_incidents(recent, "live"),
                                                {k: v for k, v in live_existing.items() if v.site_id == site_id})
        for inc in rebuilt:
            prev = live_existing.get(inc.incident_id)
            if prev is not None and prev.detection_keys == inc.detection_keys and prev.smoke is not None:
                inc = inc.model_copy(update={"smoke": prev.smoke, "receptor_ids": prev.receptor_ids})
            else:
                shape = shapes[site_id]
                try:
                    hours, grid = wind.parse_hourly(forecast(shape.centroid_lat, shape.centroid_lon))
                except Exception as exc:
                    log_json("wind_error", site_id=site_id, error=f"{type(exc).__name__}: {exc}"[:200])
                    hours, grid = [], None
                sel = pipeline.wind_hours_for(inc, recent, hours, now=now)
                inc, _ = pipeline.enrich(inc, shape, sel, grid, rc.load_receptors(site_id), now)
            store.put_incident(inc)
            (updated if prev is not None else created).append(inc.incident_id)
            log_json("incident_updated", incident_id=inc.incident_id, status=inc.status, mode=inc.mode,
                     new=prev is None, overpasses=inc.overpass_count, receptors_in_zone=len(inc.receptor_ids))

    latest = [s["latest_acq_utc"] for s in sources.values() if s.get("latest_acq_utc")]
    rec = {
        "scan_utc": utc_iso(now),
        "sources": sources,
        "raw_detections": len(all_dets),
        "matched_detections": len(matched),
        "sites_monitored": len(sites),
        "incidents_created": created,
        "incidents_updated": updated,
        "latest_detection_utc": max(latest) if latest else None,
        "duration_s": round(time.monotonic() - t0, 2),
        "config_hash": config_hash(),
    }
    store.put_scan(rec)
    log_json("scan_done", **{k: v for k, v in rec.items() if k != "sources"})
    return rec

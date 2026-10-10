"""Group matched detections into incidents and compute their status (MVP §6.3). Pure functions.

Only code sets CANDIDATE and PROBABLE. CONFIRMED, FALSE_ALARM and CLOSED come only from a person
through the API (HumanAction); `apply_human_actions` carries them over when incidents are rebuilt.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from lfw.config import (
    CANDIDATE_MIN_LOW_OVERPASSES,
    FRP_HIGH_MW,
    INCIDENT_GAP_H,
    OVERPASS_MERGE_MINUTES,
    PROBABLE_MIN_OVERPASSES,
    PROBABLE_WINDOW_H,
)
from lfw.models import Detection, Incident, Mode

OverpassId = tuple[str, str, datetime]  # (source, satellite, first acquisition time of the pass)


def overpass_ids(dets: Iterable[Detection], merge_minutes: int = OVERPASS_MERGE_MINUTES) -> dict[str, OverpassId]:
    """Map detection key -> overpass id. Same source+satellite within merge_minutes = one pass."""
    by_sat: dict[tuple[str, str], list[Detection]] = defaultdict(list)
    for d in dets:
        by_sat[(d.source, d.satellite)].append(d)
    out: dict[str, OverpassId] = {}
    merge = timedelta(minutes=merge_minutes)
    for (source, sat), group in by_sat.items():
        group.sort(key=lambda d: d.acq_utc)
        start = prev = None
        for d in group:
            if start is None or d.acq_utc - prev > merge:
                start = d.acq_utc
            prev = d.acq_utc
            out[d.key] = (source, sat, start)
    return out


def _probable_pair(times: list[datetime]) -> datetime | None:
    """Time at which >= PROBABLE_MIN_OVERPASSES distinct overpasses fall within PROBABLE_WINDOW_H."""
    times = sorted(times)
    k = PROBABLE_MIN_OVERPASSES
    for i in range(k - 1, len(times)):
        if times[i] - times[i - k + 1] <= timedelta(hours=PROBABLE_WINDOW_H):
            return times[i]
    return None


def evaluate(dets: list[Detection], ov: Mapping[str, OverpassId]) -> tuple[str | None, datetime | None, datetime | None, str]:
    """Status of one time-ordered cluster. Returns (status, candidate_utc, probable_utc, reason).

    CANDIDATE: >= 1 nominal/high detection, or low detections from >= 2 distinct overpasses.
    PROBABLE: detections from >= 2 distinct overpasses within 24 h, or one high detection with
    FRP >= FRP_HIGH_MW. Evaluated in time order so the first time each level is reached is known.
    """
    candidate_utc = probable_utc = None
    reasons: list[str] = []
    seen_ov: dict[OverpassId, datetime] = {}
    low_ov: set[OverpassId] = set()
    for d in dets:
        o = ov[d.key]
        seen_ov.setdefault(o, o[2])
        if d.confidence_tier == "low":
            low_ov.add(o)
        if candidate_utc is None:
            if d.confidence_tier in ("nominal", "high"):
                candidate_utc = d.acq_utc
                reasons.append(f"CANDIDATE: {d.confidence_tier} detection at {d.acq_utc:%Y-%m-%d %H:%M}Z")
            elif len(low_ov) >= CANDIDATE_MIN_LOW_OVERPASSES:
                candidate_utc = d.acq_utc
                reasons.append(f"CANDIDATE: low detections from {len(low_ov)} overpasses")
        if probable_utc is None:
            if d.confidence_tier == "high" and d.frp_mw is not None and d.frp_mw >= FRP_HIGH_MW:
                probable_utc = d.acq_utc
                reasons.append(f"PROBABLE: high detection with FRP {d.frp_mw} MW >= {FRP_HIGH_MW}")
            elif _probable_pair(list(seen_ov.values())) is not None:
                probable_utc = d.acq_utc
                reasons.append(
                    f"PROBABLE: {PROBABLE_MIN_OVERPASSES} distinct overpasses within {PROBABLE_WINDOW_H} h"
                )
    status = "PROBABLE" if probable_utc else "CANDIDATE" if candidate_utc else None
    return status, candidate_utc, probable_utc, "; ".join(reasons)


def clusters(dets: list[Detection]) -> list[list[Detection]]:
    """Split one site's detections where the gap since the previous one exceeds INCIDENT_GAP_H."""
    out: list[list[Detection]] = []
    for d in sorted(dets, key=lambda x: (x.acq_utc, x.key)):
        if out and d.acq_utc - out[-1][-1].acq_utc <= timedelta(hours=INCIDENT_GAP_H):
            out[-1].append(d)
        else:
            out.append([d])
    return out


def build_incidents(dets: Iterable[Detection], mode: Mode) -> list[Incident]:
    """All incidents for matched detections of one mode. Clusters below CANDIDATE create none."""
    by_site: dict[str, list[Detection]] = defaultdict(list)
    for d in dets:
        if d.site_id is None:
            continue
        if d.mode != mode:
            raise ValueError(f"detection {d.key} has mode {d.mode}, expected {mode}")
        by_site[d.site_id].append(d)
    incidents: list[Incident] = []
    for site_id in sorted(by_site):
        site_dets = by_site[site_id]
        ov = overpass_ids(site_dets)
        for cl in clusters(site_dets):
            status, cand, prob, reason = evaluate(cl, ov)
            if status is None:
                continue  # stored as detections only (MVP §6.3 step 4)
            frps = [d.frp_mw for d in cl if d.frp_mw is not None]
            first = cl[0].acq_utc
            incidents.append(
                Incident(
                    incident_id=f"{site_id}-{first:%Y%m%dT%H%M}",
                    site_id=site_id,
                    mode=mode,
                    status=status,
                    first_utc=first,
                    last_utc=cl[-1].acq_utc,
                    detection_keys=[d.key for d in cl],
                    overpass_count=len({ov[d.key] for d in cl}),
                    max_frp_mw=max(frps) if frps else None,
                    candidate_utc=cand,
                    probable_utc=prob,
                    status_reason=reason,
                )
            )
    return incidents


def apply_human_actions(rebuilt: list[Incident], existing: Mapping[str, Incident]) -> list[Incident]:
    """Keep a person's review (and its status) when incidents are rebuilt from detections."""
    out = []
    for inc in rebuilt:
        prev = existing.get(inc.incident_id)
        if prev is not None and prev.human_action is not None:
            inc = inc.model_copy(update={"human_action": prev.human_action, "status": prev.human_action.status})
        out.append(inc)
    return out

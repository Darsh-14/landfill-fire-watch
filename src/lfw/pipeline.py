"""Shared steps after incidents are built: smoke screening sector and receptors (pure).

Smoke for an incident is computed at the moment its code status was reached: detection hours up to
`probable_utc` (or `candidate_utc` if it never became PROBABLE), each plus REPLAY_WIND_EXTRA_HOURS
(MVP §6.4). Live incidents use the next LIVE_WIND_HOURS from the scan time instead.
"""

from __future__ import annotations

from datetime import datetime

from lfw import receptors as rc
from lfw import smoke, wind
from lfw.config import LIVE_WIND_HOURS, REPLAY_WIND_EXTRA_HOURS
from lfw.geo import SiteShape
from lfw.models import Detection, Incident, Receptor, WindHour


def status_time(inc: Incident) -> datetime:
    return inc.probable_utc or inc.candidate_utc or inc.first_utc


def wind_hours_for(inc: Incident, dets: list[Detection], all_hours: list[WindHour],
                   now: datetime | None = None) -> list[WindHour]:
    if inc.mode == "live":
        return wind.next_hours(all_hours, now or status_time(inc), LIVE_WIND_HOURS)
    keys = set(inc.detection_keys)
    cutoff = status_time(inc)
    times = [d.acq_utc for d in dets if d.key in keys and d.acq_utc <= cutoff]
    return wind.replay_hours(all_hours, times, REPLAY_WIND_EXTRA_HOURS)


def enrich(inc: Incident, shape: SiteShape, hours: list[WindHour], grid: tuple[float, float] | None,
           site_receptors: list[Receptor], computed_utc: datetime) -> tuple[Incident, list[Receptor]]:
    """Attach the smoke zone and the receptors inside it. No wind -> no zone, no receptors."""
    if not hours:
        return inc.model_copy(update={"smoke": None, "receptor_ids": []}), []
    zone = smoke.smoke_zone(shape.centroid_lat, shape.centroid_lon, hours, computed_utc, grid)
    inside = rc.in_zone(site_receptors, zone)
    return inc.model_copy(update={"smoke": zone, "receptor_ids": [r.receptor_id for r in inside]}), inside

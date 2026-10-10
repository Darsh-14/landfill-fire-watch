"""Pydantic models for every record that crosses a module boundary (MVP §5, CLAUDE.md §8).

Fields beyond MVP §5 are marked "added"; each one exists because a fixture or a metric needs it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Tier = Literal["low", "nominal", "high"]
Mode = Literal["live", "replay"]
Status = Literal["CANDIDATE", "PROBABLE", "CONFIRMED", "FALSE_ALARM", "CLOSED"]


class Site(BaseModel):
    site_id: str
    name: str
    city: str
    state: str
    polygon_path: str
    polygon_source: Literal["osm", "manual"]
    osm_id: str | None
    exclusions: list[str] = []
    verified_by: str | None = None


class Detection(BaseModel):
    key: str  # f"{source}|{acq_date}|{acq_time:04d}|{lat:.4f}|{lon:.4f}"
    source: str
    satellite: str
    instrument: Literal["VIIRS", "MODIS"]
    lat: float
    lon: float
    acq_utc: datetime
    confidence_raw: str
    confidence_tier: Tier
    frp_mw: float | None
    scan_km: float
    track_km: float
    daynight: str
    type_code: int | None
    site_id: str | None = None
    match_distance_m: float | None = None
    mode: Mode
    # added: MVP §6.1 step 5 says "flag it" for static land sources.
    static_source: bool = False
    # added: FIRMS `version` (e.g. "2.0NRT", "61.03"); kept for provenance.
    version: str | None = None


class WindHour(BaseModel):
    """One Open-Meteo hourly value (fixture: hourly.time / wind_speed_10m / wind_direction_10m)."""

    time_utc: datetime
    speed_ms: float
    from_deg: int  # direction the wind comes FROM


class SmokeZone(BaseModel):
    computed_utc: datetime
    wind_hours: list[WindHour]
    toward_deg: list[int]
    half_angle_deg: int  # the widest half-angle used
    length_km: float
    calm: bool
    geometry_geojson: dict
    # added: per-hour half-angle (30 or 45 deg) and the mean speed that decides `calm`.
    half_angles_deg: list[int] = []
    mean_speed_ms: float | None = None
    # added: Open-Meteo returns the grid point it used, which differs from the request point.
    wind_point_lat: float | None = None
    wind_point_lon: float | None = None


class HumanAction(BaseModel):
    """A person's review through POST /incidents/{id}/review (MVP §8 body: status, note)."""

    status: Literal["CONFIRMED", "FALSE_ALARM", "CLOSED"]
    note: str = ""
    utc: datetime


class Incident(BaseModel):
    incident_id: str  # f"{site_id}-{first_utc:%Y%m%dT%H%M}"
    site_id: str
    mode: Mode
    status: Status
    first_utc: datetime
    last_utc: datetime
    detection_keys: list[str]
    overpass_count: int
    max_frp_mw: float | None
    smoke: SmokeZone | None = None
    receptor_ids: list[str] = []
    human_action: HumanAction | None = None
    # added: when the code-computed status first reached each level (backtest metrics, UI timeline).
    candidate_utc: datetime | None = None
    probable_utc: datetime | None = None
    status_reason: str = ""


class Receptor(BaseModel):
    receptor_id: str  # f"osm:{type}/{id}"
    name: str | None
    kind: Literal["school", "kindergarten", "college", "hospital", "clinic"]
    lat: float
    lon: float
    distance_km: float


class RawFetch(BaseModel):
    """Provenance of one raw FIRMS CSV (cache sidecar locally, S3 metadata in AWS)."""

    source: str
    url_redacted: str
    retrieved_utc: str
    sha256: str
    bytes: int
    from_cache: bool = Field(default=False, exclude=True)

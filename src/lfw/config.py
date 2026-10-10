"""Every threshold and fixed constant, each with its reason (CLAUDE.md §8, MVP §6).

Freeze these values before the first full backtest run (MVP §10.4). `config_hash()` is printed
in every backtest output so a later change is visible. Record any change in the README.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta, timezone
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# NASA FIRMS Area API (CLAUDE.md §6; https://firms.modaps.eosdis.nasa.gov/api/area/)
# ---------------------------------------------------------------------------

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov"

# The API accepts DAY_RANGE 1..5 per call; longer periods need several calls.
FIRMS_MAX_DAY_RANGE = 5

# Live scan sources: the four NRT feeds named in CLAUDE.md §6.
LIVE_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")

# Archive (standard processing) sources for the backtest. The FIRMS API page lists no NOAA-21 SP feed.
ARCHIVE_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP")

# Live scan window: last 24 h. The 3-hour schedule overlaps on purpose; detection keys dedupe.
SCAN_DAY_RANGE = 1

# India bounding box (west, south, east, north) for the live scan. Copied from the Nominatim
# `boundingbox` of relation 304716 (India) in tests/fixtures/nominatim_india.json, 2026-10-10.
INDIA_BBOX = (67.9160885, 6.5531169, 97.3950905, 35.6729307)

# ---------------------------------------------------------------------------
# 6.1 Match a detection to a site
# ---------------------------------------------------------------------------

# Extra buffer beyond the pixel half-size r = max(scan_km, track_km) * 1000 / 2.
# MVP §6.1 default. Allows for geolocation error of the pixel centre; small next to a 375 m pixel.
MATCH_MARGIN_M = 100.0

# FIRMS `type` code for "other static land source" (FIRMS attribute page: 0 = presumed vegetation
# fire, 1 = active volcano, 2 = other static land source, 3 = offshore). Such hits are kept but
# forced to tier "low" and flagged (MVP §6.1 step 5). Fixtures: both VIIRS_SNPP_SP and MODIS_SP
# have a `type` column; NRT feeds do not (docs/data-notes.md).
STATIC_LAND_TYPE_CODES = frozenset({2})

# ---------------------------------------------------------------------------
# 6.2 Confidence tier
# ---------------------------------------------------------------------------

# VIIRS confidence is a class letter, not a number. Fixtures show `n` and `h`.
# TODO(verify): `l` is not in the P0 samples; confirm it from a larger sample in P1.
VIIRS_CONFIDENCE_TIERS = {"l": "low", "n": "nominal", "h": "high"}

# MODIS confidence is 0..100 (FIRMS attribute page). Class edges from MVP §6.2:
# < 30 low, 30..79 nominal, >= 80 high. TODO(verify) against the MODIS active fire user guide.
MODIS_NOMINAL_FROM = 30
MODIS_HIGH_FROM = 80

# ---------------------------------------------------------------------------
# 6.3 Build incidents
# ---------------------------------------------------------------------------

# Join a detection to the open incident if the gap since its last detection is at most this.
# MVP §6.3 default: a smouldering landfill can be missed for a day by cloud, smoke or orbit gaps.
INCIDENT_GAP_H = 36

# PROBABLE needs detections from this many distinct overpasses within PROBABLE_WINDOW_H.
# Two independent overpasses make a one-off artefact much less likely (MVP §6.3).
PROBABLE_MIN_OVERPASSES = 2
PROBABLE_WINDOW_H = 24

# One high-confidence detection with at least this FRP is enough for PROBABLE (MVP §6.3 default).
FRP_HIGH_MW = 10.0

# CANDIDATE from low-tier detections only needs this many distinct overpasses (MVP §6.3).
CANDIDATE_MIN_LOW_OVERPASSES = 2

# Overpass identity. MVP §5 says distinct (satellite, acq_utc). The VIIRS_SNPP_SP fixture has rows
# at 19:36 and 19:37 UTC on 2023-03-03 from the same satellite: one pass split across data granules.
# Acquisitions of the same source+satellite at most this many minutes apart count as ONE overpass.
# Successive orbits of one satellite are far more than 10 minutes apart, so real passes never merge.
# 0 = literal MVP §5 definition. DECISION PENDING (user) before the config freeze.
OVERPASS_MERGE_MINUTES = 10

# Static-land-source detections (FIRMS type 2) are forced to "low" (MVP §6.1). Read literally,
# MVP §6.3 still lets two of them from different overpasses make an incident PROBABLE. The
# Brahmapuram VIIRS_SNPP_SP fixture has two type-2 rows 23 h 41 min apart (2023-02-28 and 03-01).
# True = such detections still count for CANDIDATE (as low) but not for the PROBABLE overpass rule.
# False = literal MVP §6.3. DECISION PENDING (user) before the config freeze.
PROBABLE_EXCLUDES_STATIC = True

# ---------------------------------------------------------------------------
# 6.4 Smoke screening sector (a screening sector, NOT a dispersion model)
# ---------------------------------------------------------------------------

# Live: wind for the next N hours. Replay: each detection hour plus N hours after it (MVP §6.4).
LIVE_WIND_HOURS = 6
REPLAY_WIND_EXTRA_HOURS = 6

# Sector half-angle. Wider in light wind because direction is less stable (MVP §6.4).
SMOKE_HALF_ANGLE_DEG = 30
SMOKE_HALF_ANGLE_LOW_WIND_DEG = 45
LOW_WIND_MS = 2.0

# Mean speed below this: direction is not meaningful, so use a circle around the site (MVP §6.4).
CALM_MEAN_WIND_MS = 1.0
CALM_RADIUS_KM = 2.0

# Sector length. Brahmapuram 2023 smoke was reported up to about 10 km away (MVP §6.4, docs/claims.md).
SMOKE_LENGTH_KM = 10.0

# ---------------------------------------------------------------------------
# 6.5 Receptors
# ---------------------------------------------------------------------------

# Cache radius around each site. Larger than SMOKE_LENGTH_KM so every sector fits inside it.
RECEPTOR_RADIUS_KM = 12.0
RECEPTOR_AMENITIES = ("school", "kindergarten", "college", "hospital", "clinic")

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

# Local equirectangular projection is only used below this distance (CLAUDE.md §3).
LOCAL_PROJECTION_MAX_KM = 20.0

# IUGG mean Earth radius R1, in metres. Used by the local projection and the haversine check.
EARTH_RADIUS_M = 6_371_008.8

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

# India Standard Time is UTC+05:30 with no daylight saving. Fixed offset avoids a tzdata
# dependency on Windows. Store UTC; show IST in the UI (CLAUDE.md §6).
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

# Quiet windows: two 30-day monsoon (Jul-Sep) windows in other years per event site (MVP §10.2).
# Fixed rule chosen before any run: 15 Jul + 30 days (inside Jul-Sep at every site), in the year
# before and the year after the event, with the same archive sources as the event.
QUIET_WINDOW_DAYS = 30
QUIET_WINDOW_START_MONTH_DAY = (7, 15)
QUIET_WINDOW_YEAR_OFFSETS = (-1, 1)

# Backtest query box: site outline bounds +/- this many degrees (about 11 km of latitude). Far larger
# than any pixel half-size plus margin, so no matching detection is cut off. Area is free; FIRMS
# limits transactions, not area.
BACKTEST_BBOX_MARGIN_DEG = 0.1

# ---------------------------------------------------------------------------
# HTTP (CLAUDE.md §8: timeouts and 2 retries with backoff)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT_S = 60.0  # Overpass and India-wide FIRMS calls can take tens of seconds.
HTTP_RETRIES = 2
HTTP_BACKOFF_S = 3.0  # Doubled per retry: 3 s, then 6 s.
USER_AGENT = "LandfillFireWatch/0.1 (WeMakeDevs x AWS Environmental Hacks)"


def config_hash() -> str:
    """SHA-256 over every UPPER_CASE constant in this module, in sorted order."""
    values = {}
    for name, value in sorted(globals().items()):
        if not name.isupper():
            continue
        if isinstance(value, (frozenset, set)):
            value = sorted(value)
        elif isinstance(value, timezone):
            value = str(value)
        values[name] = value
    blob = json.dumps(values, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


class Settings(BaseSettings):
    """Runtime settings from env vars or `.env`. Secrets stay SecretStr so they never print."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    firms_map_key: SecretStr | None = None
    admin_token: SecretStr | None = None
    store: Literal["local", "dynamodb"] = "local"
    bedrock_model_id: str | None = None
    aws_region: str | None = None


def get_settings() -> Settings:
    return Settings()

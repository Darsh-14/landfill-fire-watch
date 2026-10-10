"""Hourly 10 m wind from Open-Meteo (forecast for live, archive for replay). Network lives here.

Parser written against tests/fixtures/openmeteo_*.json (docs/data-notes.md):
  * keys: latitude, longitude (grid point actually used), utc_offset_seconds, hourly_units, hourly
  * hourly: time ("2023-03-02T00:00", no zone; UTC when timezone=GMT), wind_speed_10m (m/s with
    wind_speed_unit=ms), wind_direction_10m (int degrees, direction the wind comes FROM)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lfw.http import request
from lfw.models import WindHour

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = "wind_speed_10m,wind_direction_10m"


class WindFormatError(ValueError):
    pass


def parse_hourly(payload: dict) -> tuple[list[WindHour], tuple[float, float]]:
    """Return (hours with both values present, (grid_lat, grid_lon))."""
    if payload.get("utc_offset_seconds", 0) != 0:
        raise WindFormatError("expected timezone=GMT (utc_offset_seconds = 0)")
    units = payload.get("hourly_units", {})
    if units.get("wind_speed_10m") != "m/s":
        raise WindFormatError(f"expected m/s, got {units.get('wind_speed_10m')!r}; pass wind_speed_unit=ms")
    h = payload["hourly"]
    out = []
    for t, s, d in zip(h["time"], h["wind_speed_10m"], h["wind_direction_10m"], strict=True):
        if s is None or d is None:
            continue
        out.append(WindHour(time_utc=datetime.fromisoformat(t).replace(tzinfo=UTC), speed_ms=float(s),
                            from_deg=int(round(d)) % 360))
    return out, (float(payload["latitude"]), float(payload["longitude"]))


def _params(lat: float, lon: float) -> dict:
    return {"latitude": round(lat, 6), "longitude": round(lon, 6), "hourly": HOURLY,
            "wind_speed_unit": "ms", "timezone": "GMT"}


def fetch_forecast(lat: float, lon: float) -> dict:
    return request("GET", FORECAST_URL, params={**_params(lat, lon), "forecast_days": 2}).json()


def fetch_archive(lat: float, lon: float, start: date, end: date, cache_dir: Path | None = None) -> dict:
    params = {**_params(lat, lon), "start_date": start.isoformat(), "end_date": end.isoformat()}
    if cache_dir is not None:
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
        path = cache_dir / f"archive_{start}_{end}_{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    payload = request("GET", ARCHIVE_URL, params=params).json()
    if cache_dir is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return payload


def next_hours(hours: list[WindHour], now: datetime, n: int) -> list[WindHour]:
    """Live: the next n hours from the hour containing `now` (MVP §6.4 step 1)."""
    start = now.replace(minute=0, second=0, microsecond=0)
    return [h for h in hours if h.time_utc >= start][:n]


def replay_hours(hours: list[WindHour], detection_times: list[datetime], extra: int) -> list[WindHour]:
    """Replay: every hour with a detection plus `extra` hours after it (MVP §6.4 step 1)."""
    wanted: set[datetime] = set()
    for t in detection_times:
        h0 = t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        wanted.update(h0 + timedelta(hours=i) for i in range(extra + 1))
    return [h for h in hours if h.time_utc in wanted]

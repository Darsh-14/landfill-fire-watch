"""NASA FIRMS Area API: fetch, cache and parse. Parser written against tests/fixtures/firms_*.csv.

Fixture facts this parser relies on (docs/data-notes.md):
  * VIIRS header: latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,
    confidence,version,bright_ti5,frp,daynight[,type]
  * MODIS header: latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,
    confidence,version,bright_t31,frp,daynight[,type]
  * `type` exists only in SP (archive) files.
  * `acq_time` is HHMM in UTC but not zero-padded ("450" = 04:50).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

from lfw import detect
from lfw.config import FIRMS_BASE_URL, FIRMS_MAX_DAY_RANGE
from lfw.http import request
from lfw.models import Detection, Mode, RawFetch

REQUIRED_COLUMNS = {
    "latitude", "longitude", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "frp", "daynight",
}


class FirmsFormatError(ValueError):
    """The response is not a FIRMS CSV (e.g. an error message in the body)."""


def instrument_of(source: str) -> str:
    if source.startswith("VIIRS_"):
        return "VIIRS"
    if source.startswith("MODIS_"):
        return "MODIS"
    raise ValueError(f"unsupported FIRMS source: {source}")


def acq_hhmm(raw: str) -> str:
    """'450' -> '0450'. Rejects anything that is not a valid UTC HHMM."""
    s = raw.strip().zfill(4)
    if len(s) != 4 or not s.isdigit() or int(s[:2]) > 23 or int(s[2:]) > 59:
        raise FirmsFormatError(f"bad acq_time: {raw!r}")
    return s


def detection_key(source: str, acq_date: str, hhmm: str, lat: float, lon: float) -> str:
    return f"{source}|{acq_date}|{hhmm}|{lat:.4f}|{lon:.4f}"


def _float_or_none(v: str | None) -> float | None:
    if v is None or v.strip() == "":
        return None
    return float(v)


def parse_csv(text: str, source: str, mode: Mode) -> list[Detection]:
    """Parse one FIRMS area CSV. An empty result (header only) is valid."""
    instrument = instrument_of(source)
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return []  # empty body: no detections
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise FirmsFormatError(f"{source}: missing columns {sorted(missing)}; got {reader.fieldnames}")
    out: list[Detection] = []
    for row in reader:
        if row["instrument"] != instrument:
            raise FirmsFormatError(f"{source}: row instrument {row['instrument']!r}")
        hhmm = acq_hhmm(row["acq_time"])
        lat, lon = float(row["latitude"]), float(row["longitude"])
        acq_utc = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)
        type_raw = row.get("type")
        type_code = int(type_raw) if type_raw not in (None, "") else None
        conf = row["confidence"].strip()
        tier = detect.tier(instrument, conf)
        static = detect.is_static(type_code)
        out.append(
            Detection(
                key=detection_key(source, row["acq_date"], hhmm, lat, lon),
                source=source,
                satellite=row["satellite"].strip(),
                instrument=instrument,
                lat=lat,
                lon=lon,
                acq_utc=acq_utc,
                confidence_raw=conf,
                confidence_tier="low" if static else tier,
                frp_mw=_float_or_none(row.get("frp")),
                scan_km=float(row["scan"]),
                track_km=float(row["track"]),
                daynight=row["daynight"].strip(),
                type_code=type_code,
                mode=mode,
                static_source=static,
                version=row["version"].strip(),
            )
        )
    return out


def area_url(key: str, source: str, bbox: tuple[float, float, float, float], day_range: int,
             start: date | None = None) -> str:
    if not 1 <= day_range <= FIRMS_MAX_DAY_RANGE:
        raise ValueError(f"day_range must be 1..{FIRMS_MAX_DAY_RANGE}")
    w, s, e, n = bbox
    url = f"{FIRMS_BASE_URL}/api/area/csv/{key}/{source}/{w:.4f},{s:.4f},{e:.4f},{n:.4f}/{day_range}"
    return url + (f"/{start.isoformat()}" if start else "")


def _check_body(body: bytes, source: str) -> None:
    head = body.lstrip(b"\xef\xbb\xbf").lstrip()[:200].lower()
    if head and not head.startswith(b"latitude"):
        raise FirmsFormatError(f"{source}: response is not a FIRMS CSV: {head[:120]!r}")


def fetch_area(key: str, source: str, bbox: tuple[float, float, float, float], day_range: int,
               start: date | None = None, cache_dir: Path | None = None) -> tuple[bytes, RawFetch]:
    """Fetch one area CSV. With cache_dir, reuse a cached copy (archive data does not change)."""
    url = area_url(key, source, bbox, day_range, start)
    shown = url.replace(key, "{MAP_KEY}")
    cache_csv = cache_meta = None
    if cache_dir is not None:
        w, s, e, n = bbox
        stem = f"{start.isoformat() if start else 'latest'}_{day_range}"
        folder = cache_dir / source / f"{w:.4f}_{s:.4f}_{e:.4f}_{n:.4f}"
        cache_csv, cache_meta = folder / f"{stem}.csv", folder / f"{stem}.json"
        if cache_csv.exists() and cache_meta.exists():
            body = cache_csv.read_bytes()
            meta = RawFetch(**json.loads(cache_meta.read_text(encoding="utf-8")))
            if hashlib.sha256(body).hexdigest() != meta.sha256:
                raise FirmsFormatError(f"cache SHA-256 mismatch: {cache_csv}")
            meta.from_cache = True
            return body, meta
    resp = request("GET", url, timeout=120, redact_values=(key,))  # raises redacted FetchError
    body = resp.content
    _check_body(body, source)
    meta = RawFetch(
        source=source,
        url_redacted=shown,
        retrieved_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sha256=hashlib.sha256(body).hexdigest(),
        bytes=len(body),
    )
    if cache_csv is not None and cache_meta is not None:
        cache_csv.parent.mkdir(parents=True, exist_ok=True)
        cache_csv.write_bytes(body)
        cache_meta.write_text(meta.model_dump_json(indent=1), encoding="utf-8", newline="\n")
    return body, meta

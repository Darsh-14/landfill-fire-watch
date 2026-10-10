"""Confidence tiers and detection-to-site matching. Pure functions, no network (MVP §6.1, §6.2)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lfw.config import (
    MATCH_MARGIN_M,
    MODIS_HIGH_FROM,
    MODIS_NOMINAL_FROM,
    STATIC_LAND_TYPE_CODES,
    VIIRS_CONFIDENCE_TIERS,
)
from lfw.geo import SiteShape, matches
from lfw.models import Detection, Tier


def tier(instrument: str, confidence_raw: str) -> Tier:
    """VIIRS: class letter (l/n/h). MODIS: 0..100 -> <30 low, 30..79 nominal, >=80 high."""
    raw = confidence_raw.strip()
    if instrument == "VIIRS":
        try:
            return VIIRS_CONFIDENCE_TIERS[raw.lower()]  # type: ignore[return-value]
        except KeyError:
            raise ValueError(f"unknown VIIRS confidence {confidence_raw!r}") from None
    if instrument == "MODIS":
        value = float(raw)
        if not 0 <= value <= 100:
            raise ValueError(f"MODIS confidence out of range: {confidence_raw!r}")
        if value >= MODIS_HIGH_FROM:
            return "high"
        if value >= MODIS_NOMINAL_FROM:
            return "nominal"
        return "low"
    raise ValueError(f"unknown instrument {instrument!r}")


def is_static(type_code: int | None) -> bool:
    """MVP §6.1 step 5: FIRMS type 2 = other static land source (archive files only)."""
    return type_code is not None and type_code in STATIC_LAND_TYPE_CODES


def assign(det: Detection, shapes: Mapping[str, SiteShape], margin_m: float = MATCH_MARGIN_M) -> Detection | None:
    """Match one detection to the nearest site whose buffered outline contains it (MVP §6.1)."""
    best: tuple[float, str] | None = None
    for sid in sorted(shapes):
        d = matches(shapes[sid], det.lat, det.lon, det.scan_km, det.track_km, margin_m)
        if d is not None and (best is None or d < best[0]):
            best = (d, sid)
    if best is None:
        return None
    return det.model_copy(update={"site_id": best[1], "match_distance_m": round(best[0], 1)})


def match(dets: Iterable[Detection], shapes: Mapping[str, SiteShape],
          margin_m: float = MATCH_MARGIN_M) -> list[Detection]:
    """Matched detections only, deduplicated by key (re-ingesting the same CSV is a no-op)."""
    out: dict[str, Detection] = {}
    for det in dets:
        m = assign(det, shapes, margin_m)
        if m is not None:
            out[m.key] = m
    return sorted(out.values(), key=lambda d: (d.acq_utc, d.key))

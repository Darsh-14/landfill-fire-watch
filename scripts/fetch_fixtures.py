"""Fetch real API samples into tests/fixtures/ (CLAUDE.md rule 3: fetch before you parse).

Every bounding box and coordinate is derived from fetched data (OSM site outlines in data/sites/,
Nominatim boundaries), never typed by hand. Each saved file is listed in tests/fixtures/MANIFEST.yaml
with its URL (FIRMS key redacted), retrieval time, size and SHA-256.

Usage:
  python scripts/fetch_fixtures.py [--only nominatim openmeteo firms]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, log, request, sha256_bytes, utc_now_iso

from lfw.config import FIRMS_BASE_URL, get_settings

FIX = ROOT / "tests" / "fixtures"
MANIFEST = FIX / "MANIFEST.yaml"
SITE_FOR_FIXTURES = "brahmapuram-kochi"
# Margin around the Brahmapuram outline for the archive sample: about 5.5 km of latitude.
ARCHIVE_BBOX_MARGIN_DEG = 0.05
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
WIND_VARS = "wind_speed_10m,wind_direction_10m"


def load_manifest() -> dict:
    if MANIFEST.exists():
        return yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    return {}


def save(manifest: dict, name: str, body: bytes, url_shown: str, note: str = "") -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / name).write_bytes(body)
    entry = {
        "url": url_shown,
        "retrieved_utc": utc_now_iso(),
        "bytes": len(body),
        "sha256": sha256_bytes(body),
    }
    if name.endswith(".csv"):
        lines = body.decode("utf-8", errors="replace").strip().splitlines()
        entry["data_rows"] = max(len(lines) - 1, 0)
    if note:
        entry["note"] = note
    manifest[name] = entry
    log(f"saved {name} ({len(body)} bytes)")


def site_feature(site_id: str) -> dict:
    fc = json.loads((ROOT / "data" / "sites" / f"{site_id}.geojson").read_text(encoding="utf-8"))
    return fc["features"][0]


def fetch_nominatim(manifest: dict) -> None:
    for name, params in (
        ("nominatim_india.json", {"q": "India", "featureType": "country"}),
        ("nominatim_punjab.json", {"q": "Punjab, India", "featureType": "state"}),
    ):
        params = {**params, "format": "jsonv2", "limit": 1}
        resp = request("GET", NOMINATIM, params=params)
        save(manifest, name, resp.content, str(resp.url))
        time.sleep(1.2)


def fetch_openmeteo(manifest: dict) -> None:
    props = site_feature(SITE_FOR_FIXTURES)["properties"]
    lat, lon = props["centroid_lat"], props["centroid_lon"]
    common = {"latitude": lat, "longitude": lon, "hourly": WIND_VARS, "wind_speed_unit": "ms", "timezone": "GMT"}
    resp = request("GET", OPEN_METEO_FORECAST, params={**common, "forecast_days": 1})
    save(manifest, "openmeteo_forecast_brahmapuram.json", resp.content, str(resp.url),
         "Live forecast for today at the OSM centroid of brahmapuram-kochi (forecast API is for current dates).")
    resp = request("GET", OPEN_METEO_ARCHIVE, params={**common, "start_date": "2023-03-02", "end_date": "2023-03-02"})
    save(manifest, "openmeteo_archive_brahmapuram_2023-03-02.json", resp.content, str(resp.url),
         "Archive wind for the reported start day of brahmapuram-2023 at the OSM centroid.")


def bbox_str(w: float, s: float, e: float, n: float) -> str:
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def fetch_firms(manifest: dict) -> None:
    key_secret = get_settings().firms_map_key
    key = key_secret.get_secret_value() if key_secret else ""
    if not key:
        log("FIRMS_MAP_KEY is empty in .env; skipping FIRMS fixtures")
        return

    def get(path: str, name: str, note: str = "") -> None:
        url = f"{FIRMS_BASE_URL}{path.format(key=key)}"
        shown = f"{FIRMS_BASE_URL}{path.format(key='{MAP_KEY}')}"
        resp = request("GET", url, redact=(key,), timeout=120)
        body = resp.content
        if not body.lstrip().lower().startswith((b"source", b"latitude", b"data_id", b"country_id")):
            log(f"{name}: unexpected body start: {body[:120]!r}")
        save(manifest, name, body, shown, note)
        time.sleep(1)

    get("/api/data_availability/csv/{key}/ALL", "firms_data_availability_all.csv")

    punjab = json.loads((FIX / "nominatim_punjab.json").read_text(encoding="utf-8"))[0]
    s, n, w, e = (float(x) for x in punjab["boundingbox"])  # Nominatim order: south, north, west, east
    live_bbox = bbox_str(w, s, e, n)
    for src in ("VIIRS_SNPP_NRT", "MODIS_NRT"):
        get(f"/api/area/csv/{{key}}/{src}/{live_bbox}/1", f"firms_live_{src}_punjab.csv",
            "Live sample, day range 1, bbox = Nominatim boundingbox of Punjab, India "
            "(chosen because crop-residue burning makes empty samples unlikely in October).")

    w0, s0, e0, n0 = _bounds(SITE_FOR_FIXTURES)
    m = ARCHIVE_BBOX_MARGIN_DEG
    arch_bbox = bbox_str(w0 - m, s0 - m, e0 + m, n0 + m)
    for src in ("VIIRS_SNPP_SP", "MODIS_SP"):
        get(f"/api/area/csv/{{key}}/{src}/{arch_bbox}/5/2023-02-27",
            f"firms_archive_{src}_brahmapuram_2023-02-27.csv",
            "Archive sample: returns 2023-02-27 .. 2023-03-03 (DATE .. DATE+DAY_RANGE-1), "
            f"bbox = OSM outline bounds of {SITE_FOR_FIXTURES} + {m} deg.")


def _bounds(site_id: str) -> tuple[float, float, float, float]:
    from shapely.geometry import shape

    return shape(site_feature(site_id)["geometry"]).bounds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=["nominatim", "openmeteo", "firms"])
    args = ap.parse_args()
    manifest = load_manifest()
    try:
        if "nominatim" in args.only:
            fetch_nominatim(manifest)
        if "openmeteo" in args.only:
            fetch_openmeteo(manifest)
        if "firms" in args.only:
            fetch_firms(manifest)
    finally:
        MANIFEST.write_text(
            "# Real API samples saved by scripts/fetch_fixtures.py. FIRMS key redacted as {MAP_KEY}.\n"
            + yaml.safe_dump(dict(sorted(manifest.items())), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

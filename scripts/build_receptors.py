"""Cache schools, kindergartens, colleges, hospitals and clinics within 12 km of each site (MVP §6.5).

One Overpass query per site, saved to data/receptors/<site_id>.geojson (OSM-derived, ODbL).
Names come only from OSM tags (`name:en`, else `name`); missing names stay empty and are shown as
"Unnamed <kind> (OSM)". Distances are from the site centroid (local projection).

Usage:
  python scripts/build_receptors.py [--only SITE_ID ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, log, utc_now_iso  # noqa: E402
from build_sites import ATTRIBUTION, overpass  # noqa: E402

from lfw.config import RECEPTOR_AMENITIES, RECEPTOR_RADIUS_KM  # noqa: E402
from lfw.geo import LocalProjection  # noqa: E402
from lfw.sites import load_shapes, load_sites  # noqa: E402

OUT_DIR = ROOT / "data" / "receptors"


def query(lat: float, lon: float) -> str:
    kinds = "|".join(RECEPTOR_AMENITIES)
    r = int(RECEPTOR_RADIUS_KM * 1000)
    return f'[out:json][timeout:180];nwr["amenity"~"^({kinds})$"](around:{r},{lat:.6f},{lon:.6f});out tags center;'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    sites = [s for s in load_sites() if args.only is None or s.site_id in args.only]
    shapes = load_shapes(sites)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for s in sites:
        sh = shapes[s.site_id]
        log(f"[{s.site_id}] receptors within {RECEPTOR_RADIUS_KM} km of {sh.centroid_lat:.6f},{sh.centroid_lon:.6f}")
        data = overpass(query(sh.centroid_lat, sh.centroid_lon))
        proj = LocalProjection(sh.centroid_lat, sh.centroid_lon)
        feats = []
        for el in data.get("elements", []):
            if el["type"] == "node":
                lat, lon = el["lat"], el["lon"]
            elif "center" in el:
                lat, lon = el["center"]["lat"], el["center"]["lon"]
            else:
                continue
            tags = el.get("tags", {})
            kind = tags.get("amenity")
            if kind not in RECEPTOR_AMENITIES:
                continue
            x, y = proj.xy(lat, lon)
            dist_km = (x * x + y * y) ** 0.5 / 1000.0
            if dist_km > RECEPTOR_RADIUS_KM:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                "properties": {
                    "receptor_id": f"osm:{el['type']}/{el['id']}",
                    "name": tags.get("name:en") or tags.get("name"),
                    "name_local": tags.get("name") if tags.get("name:en") else None,
                    "kind": kind,
                    "distance_km": round(dist_km, 2),
                },
            })
        feats.sort(key=lambda f: (f["properties"]["distance_km"], f["properties"]["receptor_id"]))
        fc = {
            "type": "FeatureCollection",
            "site_id": s.site_id,
            "centroid": [round(sh.centroid_lon, 6), round(sh.centroid_lat, 6)],
            "radius_km": RECEPTOR_RADIUS_KM,
            "retrieved_utc": utc_now_iso(),
            "source": "OpenStreetMap via Overpass API",
            "license": "ODbL-1.0",
            "attribution": ATTRIBUTION,
            "features": feats,
        }
        (OUT_DIR / f"{s.site_id}.geojson").write_text(json.dumps(fc, ensure_ascii=False, indent=1) + "\n",
                                                      encoding="utf-8", newline="\n")
        kinds = {k: sum(f["properties"]["kind"] == k for f in feats) for k in RECEPTOR_AMENITIES}
        named = sum(1 for f in feats if f["properties"]["name"])
        log(f"[{s.site_id}] {len(feats)} receptors ({named} named): {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

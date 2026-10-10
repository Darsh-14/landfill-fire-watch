"""List possible non-landfill heat sources near each site, from OpenStreetMap (for `exclusions`).

A person reads the list and writes short notes into `exclusions` in data/sites.yaml. Nothing here
changes matching. Distances are measured to the site's candidate file (named outline plus nearby
landfill polygons). Output: data/sites/_candidates/heat_sources.yaml (OSM-derived, ODbL).

Usage:
  python scripts/nearby_heat_sources.py [--only SITE_ID ...] [--radius 3000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import log, utc_now_iso
from build_sites import CANDIDATES_DIR, REPORT, element_geometry, overpass

from lfw import geo

OUT = CANDIDATES_DIR / "heat_sources.yaml"

# OSM tags that often mark a heat source a satellite can see. Solar and wind generators are dropped.
FILTERS = (
    '["power"="plant"]',
    '["power"="generator"]["generator:source"!~"^(solar|wind)$"]',
    '["landuse"="industrial"]',
    '["man_made"~"^(works|chimney|kiln|flare)$"]',
    '["amenity"="crematorium"]',
    '["industrial"]',
)
KEEP_TAGS = ("power", "generator:source", "plant:source", "landuse", "industrial", "man_made", "amenity", "operator")


def query(ids: list[str], radius: int) -> str:
    sel = "".join(f"{t}({n});" for t, n in (i.split("/") for i in ids))
    parts = "".join(f"nwr{f}(around.s:{radius});" for f in FILTERS)
    return f"[out:json][timeout:120];({sel})->.s;({parts});out tags geom;"


def feature_geometry(el: dict):
    g = element_geometry(el)
    if g is not None:
        return g
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el.get("geometry"):
        return LineString([(p["lon"], p["lat"]) for p in el["geometry"]])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--radius", type=int, default=3000)
    args = ap.parse_args()
    report = yaml.safe_load(REPORT.read_text(encoding="utf-8"))
    out = (yaml.safe_load(OUT.read_text(encoding="utf-8")) if OUT.exists() else None) or {}
    for sid, rec in report.items():
        if (args.only is not None and sid not in args.only) or not rec.get("candidates"):
            continue
        ids = [c["osm_id"] for c in rec["candidates"]] + [n["osm_id"] for n in rec.get("nearby_landfills", [])]
        fc = json.loads((CANDIDATES_DIR / f"{sid}.geojson").read_text(encoding="utf-8"))
        site_geom = unary_union([shape(f["geometry"]) for f in fc["features"]])
        proj = geo.projection_for(site_geom)
        site_m = proj.forward(site_geom)
        log(f"[{sid}] heat sources within {args.radius} m of {ids}")
        found = []
        for el in overpass(query(ids, args.radius)).get("elements", []):
            g = feature_geometry(el)
            if g is None:
                continue
            tags = el.get("tags", {})
            found.append({
                "osm_id": f"{el['type']}/{el['id']}",
                "name": tags.get("name"),
                "tags": {k: tags[k] for k in KEEP_TAGS if k in tags},
                "distance_to_site_m": round(site_m.distance(proj.forward(g))),
                "area_ha": round(geo.area_ha(g), 2) if g.geom_type in ("Polygon", "MultiPolygon") else None,
            })
        found.sort(key=lambda x: x["distance_to_site_m"])
        out[sid] = {"retrieved_utc": utc_now_iso(), "radius_m": args.radius, "measured_from": ids, "features": found}
        log(f"[{sid}] {len(found)} features")
    OUT.write_text(
        "# Possible heat sources near each site, from OpenStreetMap (© OpenStreetMap contributors, ODbL).\n"
        "# Review aid for `exclusions` in data/sites.yaml. Written by scripts/nearby_heat_sources.py.\n"
        + yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

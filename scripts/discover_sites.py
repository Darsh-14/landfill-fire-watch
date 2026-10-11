"""Find more landfills to monitor: every named landuse=landfill area in India in OpenStreetMap.

Never invents a site. One Overpass query returns all named landfill ways and relations in India;
each outline comes from that response. Kept when:
  * area >= MIN_AREA_HA (smaller dumps are below what a 375 m VIIRS pixel can separate), and
  * it is not already monitored (no overlap with, and more than NEAR_EXISTING_M from, a current outline).
Same-name pieces within MERGE_M of each other are joined into one outline (split OSM polygons).
City and state come from Nominatim reverse geocoding of the centroid; missing ones are TODO(verify).

New sites get `verified_by: null`: the dashboard shows them dashed ("Outline not checked") until a
person checks them on imagery. Every element and the decision taken is written to
data/sites_discovery_report.yaml.

Usage: python scripts/discover_sites.py [--min-area-ha 20] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, FetchError, log, utc_now_iso
from build_sites import (
    INDIA_AREA, SITES_DIR, SITES_YAML, describe, element_geometry, feature, load_existing, nominatim,
    overpass, write_geojson,
)

from lfw import geo
from lfw.sites import load_outline, load_sites

MIN_AREA_HA = 20.0
NEAR_EXISTING_M = 1000.0  # closer than this to a monitored outline = the same landfill
MERGE_M = 1000.0          # same-name pieces closer than this are one landfill
# OSM also tags industrial waste as landuse=landfill. WeSave watches municipal solid waste, which
# burns; ash ponds, slag and mine tailings sit next to plants whose heat would read as hotspots.
INDUSTRIAL = re.compile(r"\b(fly ?ash|ash|slag|tailings?|spoil|cyanide|mine|red mud|sludge)\b", re.I)
# A name made only of these words says nothing on its own ("Municipal Landfill"); the city is prefixed.
GENERIC = {"municipal", "landfill", "dump", "dumping", "dumpyard", "ground", "yard", "site", "garbage", "waste"}
REPORT = ROOT / "data" / "sites_discovery_report.yaml"
CACHE = ROOT / "cache" / "osm" / "landfills_india.json"

QUERY = (f"[out:json][timeout:300];{INDIA_AREA}"
         '(way["landuse"="landfill"]["name"](area.in);relation["landuse"="landfill"]["name"](area.in););'
         "out tags geom;")


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def display_name(tags: dict) -> str:
    for k in ("name:en", "name"):
        v = (tags.get(k) or "").strip()
        if v and v.isascii():
            return v
    return (tags.get("name") or "").strip()


def place_of(lat: float, lon: float) -> tuple[str | None, str | None]:
    data = nominatim("reverse", {"lat": lat, "lon": lon, "zoom": 10, "addressdetails": 1})
    for f in data.get("features", []):
        a = f["properties"].get("address") or {}
        city = a.get("city") or a.get("town") or a.get("state_district") or a.get("county") or a.get("village")
        return city, a.get("state")
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-area-ha", type=float, default=MIN_AREA_HA)
    ap.add_argument("--dry-run", action="store_true", help="report only, write no sites")
    ap.add_argument("--use-cache", action="store_true", help="reuse cache/osm/landfills_india.json")
    args = ap.parse_args()

    retrieved = utc_now_iso()
    if args.use_cache and CACHE.exists():
        raw = CACHE.read_bytes()
        log(f"using cached {CACHE.relative_to(ROOT)}")
    else:
        log("Overpass: all named landuse=landfill ways and relations in India")
        try:
            raw = json.dumps(overpass(QUERY)).encode()
        except FetchError as exc:
            log(f"Overpass unavailable: {exc}")
            return 2
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(raw)
    elements = json.loads(raw)["elements"]
    log(f"{len(elements)} named landfill elements")

    # Current outlines, projected per site for metre distances.
    existing = load_existing()
    current = [(s.site_id, load_outline(s)) for s in load_sites()]

    # Join same-name pieces that lie close together.
    pieces = []
    for el in elements:
        g = element_geometry(el)
        if g is None or g.is_empty:
            continue
        pieces.append({"el": el, "g": g, "name": display_name(el.get("tags", {}))})
    groups: list[dict] = []
    for p in pieces:
        for grp in groups:
            if slug(grp["name"]) == slug(p["name"]):
                proj = geo.projection_for(grp["g"])
                if proj.forward(grp["g"]).distance(proj.forward(p["g"])) <= MERGE_M:
                    grp["g"] = unary_union([grp["g"], p["g"]])
                    grp["ids"].append(f"{p['el']['type']}/{p['el']['id']}")
                    break
        else:
            groups.append({"name": p["name"], "g": p["g"], "el": p["el"], "ids": [f"{p['el']['type']}/{p['el']['id']}"]})

    decisions, kept = [], []
    for grp in groups:
        g = grp["g"]
        area = geo.area_ha(g)
        rec = {"osm_id": "+".join(grp["ids"]), "osm_name": grp["name"], "area_ha": round(area, 1)}
        if area < args.min_area_ha:
            rec["decision"] = f"skipped: {area:.1f} ha < {args.min_area_ha:g} ha"
        elif INDUSTRIAL.search(grp["name"]):
            rec["decision"] = "skipped: industrial waste by name (ash, slag, tailings, mine spoil), not municipal"
        else:
            proj = geo.projection_for(g)
            near = [sid for sid, og in current if proj.forward(og).distance(proj.forward(g)) <= NEAR_EXISTING_M]
            if near:
                rec["decision"] = f"skipped: already monitored as {near[0]}"
            else:
                rec["decision"] = "kept"
                kept.append((grp, rec))
        decisions.append(rec)
    log(f"kept {len(kept)} of {len(groups)} (min {args.min_area_ha:g} ha, not already monitored)")

    sites_out = dict(existing)
    used = set(sites_out)
    for grp, rec in kept:
        info = describe(grp["el"], grp["g"])
        info["osm_id"] = rec["osm_id"]
        city, state = place_of(info["centroid_lat"], info["centroid_lon"])
        rec.update(city=city, state=state, centroid=[info["centroid_lat"], info["centroid_lon"]])
        name = grp["name"]
        if city and set(slug(name).split("-")) <= GENERIC:
            name = f"{city} {name}"
        rec["display_name"] = name
        sid = slug(f"{grp['name']}-{city or ''}")[:60].strip("-") or slug(rec["osm_id"])
        base, n = sid, 2
        while sid in used:
            sid, n = f"{base}-{n}", n + 1
        used.add(sid)
        rec["site_id"] = sid
        log(f"  {sid}: {name} ({rec['area_ha']} ha) {city}, {state}")
        if args.dry_run:
            continue
        info["state"] = state
        write_geojson(SITES_DIR / f"{sid}.geojson", [feature(sid, info, grp["g"], retrieved)])
        sites_out[sid] = {
            "site_id": sid, "name": name, "city": city or "TODO(verify)", "state": state or "TODO(verify)",
            "polygon_path": f"data/sites/{sid}.geojson", "polygon_source": "osm", "osm_id": rec["osm_id"],
            "exclusions": [], "verified_by": None,
        }

    REPORT.write_text(
        "# Output of scripts/discover_sites.py: every named OSM landfill in India and the decision taken.\n"
        + yaml.safe_dump({"retrieved_utc": retrieved, "query": QUERY,
                          "response_sha256": hashlib.sha256(raw).hexdigest(), "min_area_ha": args.min_area_ha,
                          "near_existing_m": NEAR_EXISTING_M, "merge_m": MERGE_M, "elements": len(elements),
                          "groups": len(groups), "kept": len(kept), "decisions": decisions},
                         sort_keys=False, allow_unicode=True),
        encoding="utf-8", newline="\n")
    if not args.dry_run:
        SITES_YAML.write_text(
            "# Monitored landfills. Built by scripts/build_sites.py and scripts/discover_sites.py; `verified_by`\n"
            "# is set after checking the outline on satellite imagery. Outlines: © OpenStreetMap contributors (ODbL).\n"
            + yaml.safe_dump(list(sites_out.values()), sort_keys=False, allow_unicode=True),
            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

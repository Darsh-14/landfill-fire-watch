"""Build landfill outlines from OpenStreetMap (Overpass API, landuse=landfill).

Never invents an outline. A site gets `data/sites/<site_id>.geojson` only when:
  * exactly one OSM landfill element in India matches its name patterns, or
  * a person picks polygons from the saved candidates file with
    `--pick <site_id>=<type>/<id>[+<type>/<id>]` (several ids are joined into one outline).
No match, or several matches, is recorded in `data/sites_build_report.yaml` with all candidates
(written to `data/sites/_candidates/<site_id>.geojson` for map review).

A search never replaces an outline that has `verified_by` set: the report records the difference
and the checked outline stays until a person re-picks it with `--pick`.

Search order: Overpass name search over India. If every Overpass endpoint fails (busy servers),
fall back to Nominatim free-text search, keep only landuse=landfill results whose name matches the
patterns, and record method "nominatim" so a person knows the completeness check was weaker.

Usage:
  python scripts/build_sites.py [--only SITE_ID ...]
  python scripts/build_sites.py --only SITE_ID --pick SITE_ID=way/1+way/2 --picked-by NAME
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import shapely
import yaml
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, FetchError, log, request, utc_now_iso

from lfw import geo

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
SEEDS = ROOT / "data" / "site_seeds.yaml"
SITES_YAML = ROOT / "data" / "sites.yaml"
SITES_DIR = ROOT / "data" / "sites"
CANDIDATES_DIR = SITES_DIR / "_candidates"
REPORT = ROOT / "data" / "sites_build_report.yaml"

# Fallback search radius around OSM place nodes with the site name, when no landfill carries the name.
PROXIMITY_RADIUS_M = 3000
# Radius for listing other landfill polygons near a candidate (split outlines, neighbouring dumps).
NEARBY_RADIUS_M = 3000
NAME_KEYS = "^(name|name:en|alt_name|old_name|official_name)$"
INDIA_AREA = 'area["ISO3166-1"="IN"]["admin_level"="2"]->.in;'
ATTRIBUTION = "© OpenStreetMap contributors"


_overpass_down = False  # circuit breaker: after a full failure, skip Overpass for the rest of the run


def overpass(query: str) -> dict:
    global _overpass_down
    if _overpass_down:
        raise FetchError("Overpass marked unavailable earlier in this run")
    errors = []
    for url in OVERPASS_URLS:
        try:
            resp = request("POST", url, data={"data": query}, timeout=200)
            time.sleep(2)  # be polite to the public Overpass instances
            return resp.json()
        except FetchError as exc:
            errors.append(str(exc)[:160])
            log(f"  overpass failed: {errors[-1]}")
    _overpass_down = True
    raise FetchError(" | ".join(errors))


def nominatim(path: str, params: dict) -> dict:
    """Nominatim usage policy: max 1 request/s, identifying User-Agent."""
    resp = request("GET", f"{NOMINATIM_URL}/{path}", params={"format": "geojson", **params}, timeout=60)
    time.sleep(1.2)
    return resp.json()


def nominatim_search(seed: dict) -> list[tuple[dict, BaseGeometry]]:
    regex = re.compile("|".join(re.escape(p) for p in seed["patterns"]), re.I)
    found: dict[str, tuple[dict, BaseGeometry]] = {}
    for q in seed.get("nominatim_queries", seed["patterns"]):
        data = nominatim(
            "search",
            {"q": q, "countrycodes": "in", "limit": 40, "polygon_geojson": 1,
             "extratags": 1, "namedetails": 1, "addressdetails": 1, "dedupe": 0},
        )
        for f in data.get("features", []):
            p = f["properties"]
            if (p.get("category"), p.get("type")) != ("landuse", "landfill"):
                continue
            names = [p.get("name") or ""] + list((p.get("namedetails") or {}).values())
            if not any(regex.search(n) for n in names):
                continue
            g = shape(f["geometry"])
            if g.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            g = g if g.is_valid else shapely.make_valid(g)
            tags = {**(p.get("extratags") or {}), **(p.get("namedetails") or {}), "landuse": "landfill"}
            el = {"type": p["osm_type"], "id": p["osm_id"], "tags": tags,
                  "_state": (p.get("address") or {}).get("state")}
            found[f"{p['osm_type']}/{p['osm_id']}"] = (el, g)
    return list(found.values())


def nominatim_state(osm_id: str) -> str | None:
    kind, num = osm_id.split("/")
    data = nominatim("lookup", {"osm_ids": f"{kind[0].upper()}{num}", "addressdetails": 1})
    for f in data.get("features", []):
        return (f["properties"].get("address") or {}).get("state")
    return None


REGEX_SPECIAL = set(".^$*+?()[]{}|\\")


def ql_regex(text: str) -> str:
    """A literal name as an Overpass QL regex inside a double-quoted QL string.

    re.escape() is not used: it also escapes spaces, and a backslash-space is not a valid escape in a
    QL string. Regex metacharacters get one backslash; then every backslash and double quote is
    escaped again for the QL string literal itself.
    """
    rx = "".join("\\" + ch if ch in REGEX_SPECIAL else ch for ch in text)
    return rx.replace("\\", "\\\\").replace('"', '\\"')


def name_query(pattern: str) -> str:
    return (
        f"[out:json][timeout:180];{INDIA_AREA}"
        f'nwr["landuse"="landfill"][~"{NAME_KEYS}"~"{pattern}",i](area.in);'
        "out tags geom;"
    )


def proximity_query(pattern: str) -> str:
    return (
        f"[out:json][timeout:180];{INDIA_AREA}"
        f'node["place"][~"^(name|name:en)$"~"{pattern}",i](area.in)->.anchor;'
        ".anchor out tags center;"
        f'nwr["landuse"="landfill"](around.anchor:{PROXIMITY_RADIUS_M});'
        "out tags geom;"
    )


def element_geometry(el: dict) -> BaseGeometry | None:
    """Polygon for a closed way or a multipolygon relation, in (lon, lat). None otherwise."""
    if el["type"] == "way":
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            g = Polygon(coords)
            return g if g.is_valid else shapely.make_valid(g)
        return None
    if el["type"] == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            line = LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
            (inners if m.get("role") == "inner" else outers).append(line)
        if not outers:
            return None
        g = unary_union(list(polygonize(unary_union(outers))))
        if inners:
            g = g.difference(unary_union(list(polygonize(unary_union(inners)))))
        if g.is_empty:
            return None
        return g if g.is_valid else shapely.make_valid(g)
    return None


def state_of(el: dict, osm_id: str) -> str | None:
    """State from the Nominatim address of the element (one light request, independent of Overpass)."""
    if el.get("_state"):
        return el["_state"]
    return nominatim_state(osm_id)


def describe(el: dict, g: BaseGeometry) -> dict:
    lat, lon = geo.centroid_latlon(g)
    minx, miny, maxx, maxy = g.bounds
    tags = el.get("tags", {})
    return {
        "osm_id": f"{el['type']}/{el['id']}",
        "osm_name": tags.get("name"),
        "osm_name_en": tags.get("name:en"),
        "area_ha": round(geo.area_ha(g), 2),
        "centroid_lat": round(lat, 6),
        "centroid_lon": round(lon, 6),
        "bbox_wsen": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
        "geometry_type": g.geom_type,
        "tags": tags,
    }


def feature(site_id: str, info: dict, g: BaseGeometry, retrieved: str) -> dict:
    props = {k: v for k, v in info.items() if k not in ("bbox_wsen",)}
    props.update(
        site_id=site_id,
        retrieved_utc=retrieved,
        source="OpenStreetMap via Overpass API",
        license="ODbL-1.0",
        attribution=ATTRIBUTION,
    )
    return {"type": "Feature", "id": info["osm_id"], "geometry": mapping(g), "properties": props}


def write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "attribution": ATTRIBUTION, "license": "ODbL-1.0", "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def search(seed: dict) -> tuple[str, list[tuple[dict, BaseGeometry]], list[dict]]:
    """Return (method, candidates, anchors). Candidates are (element, geometry) with an outline."""
    found: dict[str, tuple[dict, BaseGeometry]] = {}
    try:
        for pattern in seed["patterns"]:
            for el in overpass(name_query(ql_regex(pattern))).get("elements", []):
                g = element_geometry(el)
                if g is not None:
                    found[f"{el['type']}/{el['id']}"] = (el, g)
    except FetchError:
        log("  all Overpass endpoints failed; falling back to Nominatim name search")
        return "nominatim", nominatim_search(seed), []
    if found:
        return "name", list(found.values()), []
    anchors: list[dict] = []
    for pattern in seed["patterns"]:
        for el in overpass(proximity_query(ql_regex(pattern))).get("elements", []):
            if el["type"] == "node" and "place" in el.get("tags", {}):
                anchors.append({"osm_id": f"node/{el['id']}", "name": el["tags"].get("name"),
                                "place": el["tags"].get("place"), "lat": el["lat"], "lon": el["lon"]})
                continue
            g = element_geometry(el)
            if g is not None:
                found[f"{el['type']}/{el['id']}"] = (el, g)
    return "proximity", list(found.values()), anchors


def load_existing() -> dict[str, dict]:
    if not SITES_YAML.exists():
        return {}
    return {s["site_id"]: s for s in (yaml.safe_load(SITES_YAML.read_text(encoding="utf-8")) or [])}


def nearby_query(osm_id: str) -> str:
    kind, num = osm_id.split("/")
    return (
        f"[out:json][timeout:90];{kind}({num})->.s;"
        f'nwr["landuse"="landfill"](around.s:{NEARBY_RADIUS_M});'
        "out tags geom;"
    )


def nearby_landfills(info: dict, g: BaseGeometry) -> tuple[list[tuple[dict, BaseGeometry]], str]:
    """Other landuse=landfill elements within NEARBY_RADIUS_M (named or not), for human review."""
    try:
        data = overpass(nearby_query(info["osm_id"]))
    except FetchError:
        return [], "not run (Overpass unavailable)"
    proj = geo.projection_for(g)
    base = proj.forward(g)
    out = []
    for el in data.get("elements", []):
        oid = f"{el['type']}/{el['id']}"
        if oid == info["osm_id"]:
            continue
        ng = element_geometry(el)
        if ng is None:
            continue
        d = describe(el, ng)
        d["distance_to_chosen_m"] = round(base.distance(proj.forward(ng)), 1)
        d["intersects_chosen"] = bool(base.intersects(proj.forward(ng)))
        out.append((d, ng))
    return out, "ok"


def protects_verified(prev_site: dict, chosen_osm_id: str) -> bool:
    """True when an automatic search result must not replace an outline that was checked on a map."""
    return bool(prev_site.get("verified_by")) and prev_site.get("osm_id") != chosen_osm_id


def write_site(seed: dict, chosen: tuple[dict, BaseGeometry], retrieved: str,
               existing: dict[str, dict], sites_out: dict[str, dict]) -> None:
    sid = seed["site_id"]
    info, g = chosen
    write_geojson(SITES_DIR / f"{sid}.geojson", [feature(sid, info, g, retrieved)])
    prev = existing.get(sid, {})
    same = prev.get("osm_id") == info["osm_id"]
    sites_out[sid] = {
        "site_id": sid,
        # keep a curated display name while the outline is unchanged
        "name": prev.get("name", seed["name"]) if same else seed["name"],
        "city": seed["city"],
        "state": info["state"] or "TODO(verify)",
        "polygon_path": f"data/sites/{sid}.geojson",
        "polygon_source": "osm",
        "osm_id": info["osm_id"],
        "exclusions": prev.get("exclusions", []) if same else [],
        # A changed outline must be checked on a map again.
        "verified_by": prev.get("verified_by") if same else None,
    }


def pick_from_candidates(sid: str, ids: list[str]) -> tuple[dict, BaseGeometry] | None:
    """Union of the chosen polygons from data/sites/_candidates/<sid>.geojson."""
    path = CANDIDATES_DIR / f"{sid}.geojson"
    if not path.exists():
        log(f"[{sid}] no candidates file; run a search first")
        return None
    feats = {f["id"]: f for f in json.loads(path.read_text(encoding="utf-8"))["features"]}
    missing = [i for i in ids if i not in feats]
    if missing:
        log(f"[{sid}] --pick {missing} not in {path.name}; nothing written")
        return None
    parts = [feats[i] for i in ids]
    g = unary_union([shape(f["geometry"]) for f in parts])
    g = g if g.is_valid else shapely.make_valid(g)
    first = parts[0]["properties"]
    info = describe({"type": "pick", "id": 0, "tags": first.get("tags", {})}, g)
    info.update(
        osm_id="+".join(ids),
        osm_name=first.get("osm_name"),
        state=next((f["properties"].get("state") for f in parts if f["properties"].get("state")), None),
    )
    return info, g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=None, help="site_ids to build (default: all seeds)")
    ap.add_argument("--pick", nargs="*", default=[],
                    help="SITE_ID=type/id[+type/id] chosen from the saved candidates file")
    ap.add_argument("--picked-by", default=None, help="who made the --pick choice (recorded in the report)")
    args = ap.parse_args()

    seeds = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    picks = dict(p.split("=", 1) for p in args.pick)
    existing = load_existing()
    report = yaml.safe_load(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    report = report or {}
    sites_out = dict(existing)

    for seed in seeds:
        sid = seed["site_id"]
        if args.only is not None and sid not in args.only:
            continue
        retrieved = utc_now_iso()
        if sid in picks:
            # A person's (or delegated) choice among polygons already saved in the candidates file:
            # no new search, so the choice applies to exactly the geometry that was reviewed.
            ids = picks[sid].split("+")
            chosen = pick_from_candidates(sid, ids)
            if chosen is None:
                continue
            rec = report.get(sid, {})
            rec.update(status="picked", chosen=chosen[0]["osm_id"], picked_utc=retrieved,
                       picked_by=args.picked_by, picked_from=f"data/sites/_candidates/{sid}.geojson")
            report[sid] = rec
            write_site(seed, chosen, retrieved, existing, sites_out)
            log(f"[{sid}] picked {chosen[0]['osm_id']} ({chosen[0]['area_ha']} ha)")
            continue
        log(f"[{sid}] searching OSM for landuse=landfill named {seed['patterns']}")
        method, cands, anchors = search(seed)
        infos = []
        for el, g in cands:
            info = describe(el, g)
            info["state"] = state_of(el, info["osm_id"])
            infos.append((info, g))

        nearby: list[tuple[dict, BaseGeometry]] = []
        nearby_status = "not run (no candidates)"
        for info, g in infos:
            found_near, nearby_status = nearby_landfills(info, g)
            known = {i["osm_id"] for i, _ in infos} | {i["osm_id"] for i, _ in nearby}
            nearby += [(d, ng) for d, ng in found_near if d["osm_id"] not in known]
        for d, _ in nearby:
            d["state"] = None

        chosen: tuple[dict, BaseGeometry] | None = None
        if method in ("name", "nominatim") and len(infos) == 1:
            chosen, status = infos[0], "matched"
        elif method in ("name", "nominatim") and len(infos) > 1:
            status = "ambiguous"
        else:
            status = "no_name_match"

        CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
        cand_path = CANDIDATES_DIR / f"{sid}.geojson"
        if infos or nearby:
            feats = [feature(sid, i, g, retrieved) for i, g in infos]
            for i, g in nearby:
                f = feature(sid, i, g, retrieved)
                f["properties"]["role"] = "nearby_landfill"
                feats.append(f)
            write_geojson(cand_path, feats)
        elif cand_path.exists():
            cand_path.unlink()

        prev_site, prev_report = existing.get(sid, {}), report.get(sid, {})
        if chosen and protects_verified(prev_site, chosen[0]["osm_id"]):
            log(f"[{sid}] search found {chosen[0]['osm_id']}, but {prev_site['osm_id']} was checked on a map; "
                "keeping it (re-pick with --pick to change)")
            status, chosen = "kept_verified", None

        report[sid] = {
            "status": status,
            "method": method,
            "patterns": seed["patterns"],
            "retrieved_utc": retrieved,
            "place_anchors": anchors,
            "candidates": [{k: v for k, v in i.items() if k != "tags"} for i, _ in infos],
            "nearby_check": nearby_status,
            "nearby_landfills": [{k: v for k, v in i.items() if k != "tags"} for i, _ in nearby],
            "chosen": chosen[0]["osm_id"] if chosen else None,
        }
        if status == "kept_verified":
            report[sid]["kept_outline"] = prev_site["osm_id"]
            report[sid].update({k: prev_report[k] for k in ("picked_by", "picked_utc", "picked_from") if k in prev_report})
        log(f"[{sid}] status={status} candidates={len(infos)}")

        if chosen:
            write_site(seed, chosen, retrieved, existing, sites_out)

    SITES_YAML.write_text(
        "# Monitored landfills. Built by scripts/build_sites.py; `verified_by` is set by a person\n"
        "# after checking the outline on satellite imagery. Outlines: © OpenStreetMap contributors (ODbL).\n"
        + yaml.safe_dump(list(sites_out.values()), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    REPORT.write_text(
        "# Output of scripts/build_sites.py: every OSM search, its candidates and the decision.\n"
        + yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Schools and hospitals near each site (cached OSM GeoJSON) and selection inside a smoke zone."""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.prepared import prep

from lfw.models import Receptor, SmokeZone

ROOT = Path(__file__).resolve().parents[2]
RECEPTOR_DIR = ROOT / "data" / "receptors"


def load_receptors(site_id: str, directory: Path = RECEPTOR_DIR) -> list[Receptor]:
    path = directory / f"{site_id}.geojson"
    if not path.exists():
        return []
    fc = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        out.append(Receptor(receptor_id=p["receptor_id"], name=p.get("name"), kind=p["kind"],
                            lat=lat, lon=lon, distance_km=p["distance_km"]))
    return out


def in_zone(receptors: list[Receptor], zone: SmokeZone) -> list[Receptor]:
    """Receptors inside the screening zone, nearest to the site first (MVP §6.5 step 2)."""
    g = prep(shape(zone.geometry_geojson))
    inside = [r for r in receptors if g.covers(Point(r.lon, r.lat))]
    return sorted(inside, key=lambda r: (r.distance_km, r.receptor_id))


def display_name(r: Receptor) -> str:
    """Never invent a name (MVP §6.5 step 3)."""
    return r.name if r.name else f"Unnamed {r.kind} (OSM)"

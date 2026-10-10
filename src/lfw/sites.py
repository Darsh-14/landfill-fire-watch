"""Load monitored sites (data/sites.yaml) and their outlines (data/sites/<site_id>.geojson)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from shapely.geometry import shape
from shapely.ops import unary_union

from lfw.geo import SiteShape, site_shape
from lfw.models import Site
from lfw.paths import ROOT


def load_sites(path: Path | None = None) -> list[Site]:
    path = path or ROOT / "data" / "sites.yaml"
    return [Site(**s) for s in (yaml.safe_load(path.read_text(encoding="utf-8")) or [])]


def load_outline(site: Site, root: Path = ROOT):
    fc = json.loads((root / site.polygon_path).read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in fc["features"]]
    return geoms[0] if len(geoms) == 1 else unary_union(geoms)


def load_shapes(sites: list[Site], root: Path = ROOT) -> dict[str, SiteShape]:
    return {s.site_id: site_shape(s.site_id, load_outline(s, root)) for s in sites}

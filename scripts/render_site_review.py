"""Render site outlines on satellite imagery for the human (or delegated) outline check.

Draws every polygon in data/sites/_candidates/<site_id>.geojson on Esri World Imagery tiles:
named match in red, nearby unnamed landfill in cyan. Optional `--wayback RELEASE` uses an Esri
World Imagery Wayback release (historical imagery) instead of the current basemap.
Images go to out/review/ (git-ignored, review only, not redistributed).

Imagery: Esri World Imagery. Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community.

Usage:
  python scripts/render_site_review.py [--only SITE_ID ...] [--zoom 17] [--margin-m 400] [--wayback N]
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, log, request

CAND = ROOT / "data" / "sites" / "_candidates"
TILE_CACHE = ROOT / "cache" / "tiles"
OUT = ROOT / "out" / "review"
CURRENT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WAYBACK = ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/"
           "default028mm/MapServer/tile/{release}/{z}/{y}/{x}")
MAX_TILES = 64


def lonlat_to_px(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 256 * 2**z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile(z: int, x: int, y: int, release: int | None) -> Image.Image:
    name = f"{'cur' if release is None else f'wb{release}'}_{z}_{x}_{y}.jpg"
    path = TILE_CACHE / name
    if not path.exists():
        url = (CURRENT if release is None else WAYBACK).format(z=z, x=x, y=y, release=release)
        # Wayback redirects to the release in which the tile last changed.
        resp = request("GET", url, timeout=30, follow_redirects=True)
        if not resp.headers.get("content-type", "").startswith("image/"):
            raise RuntimeError(f"tile {z}/{x}/{y}: not an image ({resp.headers.get('content-type')})")
        TILE_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        time.sleep(0.05)
    return Image.open(io.BytesIO(path.read_bytes())).convert("RGB")


def render(site_id: str, zoom: int, margin_m: float, release: int | None) -> Path:
    fc = json.loads((CAND / f"{site_id}.geojson").read_text(encoding="utf-8"))
    geoms = [(shape(f["geometry"]), f["properties"]) for f in fc["features"]]
    w = min(g.bounds[0] for g, _ in geoms)
    s = min(g.bounds[1] for g, _ in geoms)
    e = max(g.bounds[2] for g, _ in geoms)
    n = max(g.bounds[3] for g, _ in geoms)
    dlat = margin_m / 111_320
    dlon = dlat / math.cos(math.radians((s + n) / 2))
    x0, y0 = lonlat_to_px(w - dlon, n + dlat, zoom)
    x1, y1 = lonlat_to_px(e + dlon, s - dlat, zoom)
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if count > MAX_TILES:
        raise SystemExit(f"{site_id}: {count} tiles at z{zoom}; use a lower --zoom")
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mosaic.paste(tile(zoom, tx, ty, release), ((tx - tx0) * 256, (ty - ty0) * 256))
    draw = ImageDraw.Draw(mosaic)
    for g, props in geoms:
        colour = (0, 255, 255) if props.get("role") == "nearby_landfill" else (255, 40, 40)
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        for p in polys:
            pts = [(lonlat_to_px(x, y, zoom)[0] - tx0 * 256, lonlat_to_px(x, y, zoom)[1] - ty0 * 256)
                   for x, y in p.exterior.coords]
            draw.line(pts, fill=colour, width=3)
    crop = mosaic.crop((int(x0 - tx0 * 256), int(y0 - ty0 * 256), int(x1 - tx0 * 256), int(y1 - ty0 * 256)))
    # 500 m scale bar, bottom left
    m_per_px = 156543.03392 * math.cos(math.radians((s + n) / 2)) / 2**zoom
    bar = 500 / m_per_px
    d2 = ImageDraw.Draw(crop)
    h = crop.height
    d2.rectangle((10, h - 22, 10 + bar, h - 14), fill=(255, 255, 255))
    d2.text((12, h - 38), "500 m", fill=(255, 255, 255))
    d2.text((10, 8), f"{site_id}  red = named OSM landfill, cyan = nearby unnamed landfill", fill=(255, 255, 0))
    d2.text((10, h - 12), "Imagery: Esri, Maxar, Earthstar Geographics, GIS User Community | Outlines (c) OpenStreetMap contributors", fill=(255, 255, 0))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{site_id}{'' if release is None else f'_wayback{release}'}.png"
    crop.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=["deonar-mumbai", "ghazipur-delhi", "brahmapuram-kochi"])
    ap.add_argument("--zoom", type=int, default=17)
    ap.add_argument("--margin-m", type=float, default=400)
    ap.add_argument("--wayback", type=int, default=None)
    args = ap.parse_args()
    for sid in args.only:
        z = args.zoom
        while True:
            try:
                log(f"rendered {render(sid, z, args.margin_m, args.wayback)}")
                break
            except SystemExit as exc:
                if z <= 14:
                    raise
                log(str(exc))
                z -= 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

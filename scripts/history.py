"""History stat (MVP §2.2 item 10): satellite detection-days per site from the FIRMS archive.

A detection-day is a UTC day with at least one detection matched to the site outline (same matching
code as the scan; static-land-source detections are excluded). It counts DAYS WITH A SATELLITE
HOTSPOT, not fires: one fire can span many days, and a hotspot is not a confirmed fire.

Source: VIIRS_SNPP_SP only, so every year uses the same sensor. Window: 2019-01-01 to the last
archive date in tests/fixtures/firms_data_availability_all.csv. Raw CSVs are cached (cache/firms/).

Usage: python scripts/history.py [--sites brahmapuram-kochi ...] [--start 2019-01-01]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, log, utc_now_iso
from backtest import CACHE, chunks, query_bbox

from lfw import config, detect, firms
from lfw.sites import load_shapes, load_sites

SOURCE = "VIIRS_SNPP_SP"
AVAIL = ROOT / "tests" / "fixtures" / "firms_data_availability_all.csv"
OUT = ROOT / "out"


def archive_end() -> date:
    rows = {r["data_id"]: r for r in csv.DictReader(AVAIL.open(encoding="utf-8"))}
    return date.fromisoformat(rows[SOURCE]["max_date"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="*", default=["deonar-mumbai", "ghazipur-delhi", "brahmapuram-kochi"])
    ap.add_argument("--start", default="2019-01-01")
    args = ap.parse_args()
    key = config.get_settings().firms_map_key.get_secret_value()
    start, end = date.fromisoformat(args.start), archive_end()
    sites = [s for s in load_sites() if s.site_id in args.sites]
    shapes = load_shapes(sites)
    result = {"generated_utc": utc_now_iso(), "source": SOURCE, "start": start.isoformat(), "end": end.isoformat(),
              "config_hash": config.config_hash(), "definition": "UTC days with >= 1 matched, non-static detection",
              "sites": {}}
    for s in sites:
        shape = shapes[s.site_id]
        days: Counter = Counter()
        calls = 0
        for c_start, n in chunks(start, end):
            body, meta = firms.fetch_area(key, SOURCE, query_bbox(shape), n, c_start, cache_dir=CACHE)
            calls += 1
            if not meta.from_cache:
                time.sleep(0.3)  # FIRMS limit: 5,000 transactions per 10 minutes
            dets = [d for d in firms.parse_csv(body.decode("utf-8"), SOURCE, "replay") if not d.static_source]
            for d in detect.match(dets, {s.site_id: shape}):
                days[d.acq_utc.date().isoformat()] += 1
        by_year = Counter(d[:4] for d in days)
        result["sites"][s.site_id] = {"name": s.name, "city": s.city, "detection_days": len(days),
                                      "by_year": dict(sorted(by_year.items())), "calls": calls}
        log(f"[{s.site_id}] {len(days)} detection-days {start}..{end} ({calls} calls)")
    OUT.mkdir(exist_ok=True)
    (OUT / "history.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    years = [str(y) for y in range(start.year, end.year + 1)]  # every year, so zeros are shown as zeros
    lines = ["# Satellite detection-days per site", "",
             f"VIIRS S-NPP archive (`{SOURCE}`), {start} to {end}. A detection-day is a UTC day with at least one",
             "satellite hotspot matched to the landfill outline (static-land-source pixels excluded). These are",
             "**detection-days, not fires**: one fire can last many days, and a hotspot is not a confirmation.", "",
             "| Site | Total | " + " | ".join(years) + " |", "|---|---|" + "---|" * len(years)]
    for v in result["sites"].values():
        lines.append(f"| {v['name']} ({v['city']}) | {v['detection_days']} | "
                     + " | ".join(str(v["by_year"].get(y, 0)) for y in years) + " |")
    (OUT / "history.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

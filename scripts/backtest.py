"""Backtest: replay documented fires and quiet monsoon windows from the FIRMS archive (MVP §10).

Guards (MVP §10.4, CLAUDE.md §7):
  * A publishable run needs every event site outline checked on a map (`verified_by` set in
    data/sites.yaml; see docs/site-review.md for who checked) and a config freeze
    (data/config_freeze.yaml) whose hash matches config.py.
  * `--freeze` records the freeze; config.py must be committed first.
  * `--dev` skips the guards and writes out/backtest_dev.* marked "not for publication".
  * `--event ID ...` runs a subset and writes out/backtest_partial.*, never the published report.
Raw CSVs are cached in cache/firms/ with a SHA-256 sidecar; 5-day calls (FIRMS DAY_RANGE limit).

Usage:
  python scripts/backtest.py [--event EVENT_ID ...] [--dev]
  python scripts/backtest.py --freeze
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, log, utc_now_iso

from lfw import config, detect, firms, incidents, pipeline, receptors, smoke, wind
from lfw.geo import SiteShape, distance_to_site_m, pixel_half_size_m
from lfw.models import Detection, Incident
from lfw.sites import load_shapes, load_sites

CACHE = ROOT / "cache" / "firms"
WIND_CACHE = ROOT / "cache" / "wind"
FREEZE = ROOT / "data" / "config_freeze.yaml"
EVENTS = ROOT / "data" / "events.yaml"
OUT = ROOT / "out"


# ---------------------------------------------------------------- windows and fetching


def chunks(start: date, end: date) -> list[tuple[date, int]]:
    """Inclusive [start, end] as FIRMS calls of at most FIRMS_MAX_DAY_RANGE days."""
    out, d = [], start
    while d <= end:
        n = min(config.FIRMS_MAX_DAY_RANGE, (end - d).days + 1)
        out.append((d, n))
        d += timedelta(days=n)
    return out


def quiet_windows(event: dict) -> list[tuple[date, date]]:
    year = event["reported_start"].year
    m, dd = config.QUIET_WINDOW_START_MONTH_DAY
    out = []
    for off in config.QUIET_WINDOW_YEAR_OFFSETS:
        start = date(year + off, m, dd)
        out.append((start, start + timedelta(days=config.QUIET_WINDOW_DAYS - 1)))
    return out


def query_bbox(shape: SiteShape) -> tuple[float, float, float, float]:
    w, s, e, n = shape.bounds_lonlat
    m = config.BACKTEST_BBOX_MARGIN_DEG
    return (w - m, s - m, e + m, n + m)


def fetch_window(key: str, sources: list[str], bbox, start: date, end: date) -> tuple[list[Detection], list[dict]]:
    dets: list[Detection] = []
    fetches: list[dict] = []
    for source in sources:
        for chunk_start, n in chunks(start, end):
            body, meta = firms.fetch_area(key, source, bbox, n, chunk_start, cache_dir=CACHE)
            parsed = firms.parse_csv(body.decode("utf-8"), source, "replay")
            dets += parsed
            fetches.append({**meta.model_dump(), "from_cache": meta.from_cache, "rows": len(parsed),
                            "start": chunk_start.isoformat(), "day_range": n})
    return dets, fetches


# ---------------------------------------------------------------- evaluation (pure)


def ist(dt: datetime | None) -> str | None:
    return dt.astimezone(config.IST).strftime("%Y-%m-%d %H:%M IST") if dt else None


def evaluate_window(shape: SiteShape, raw: list[Detection], start: date, end: date) -> dict:
    """Match, group and summarise one window for one site. No network."""
    in_window = [d for d in raw if start <= d.acq_utc.date() <= end]
    matched = detect.match(in_window, {shape.site_id: shape})
    incs = incidents.build_incidents(matched, "replay")
    ov = incidents.overpass_ids(matched)
    frps = [d.frp_mw for d in matched if d.frp_mw is not None]
    matched_keys = {d.key for d in matched}
    nearest = sorted(
        (
            {
                "key": d.key,
                "acq_ist": ist(d.acq_utc),
                "tier": d.confidence_tier,
                "frp_mw": d.frp_mw,
                "type_code": d.type_code,
                "distance_to_outline_m": round(distance_to_site_m(shape, d.lat, d.lon), 1),
                "match_radius_m": pixel_half_size_m(d.scan_km, d.track_km) + config.MATCH_MARGIN_M,
            }
            for d in in_window
            if d.key not in matched_keys
        ),
        key=lambda x: x["distance_to_outline_m"],
    )[:10]
    return {
        "site_id": shape.site_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "raw_in_bbox": len(in_window),
        "matched": len(matched),
        "matched_by_tier": {t: sum(d.confidence_tier == t for d in matched) for t in ("low", "nominal", "high")},
        "matched_static": sum(d.static_source for d in matched),
        "overpasses_with_detections": len(set(ov.values())),
        "max_frp_mw": max(frps) if frps else None,
        "incidents": [
            {
                "incident_id": i.incident_id,
                "status": i.status,
                "first_ist": ist(i.first_utc),
                "candidate_ist": ist(i.candidate_utc),
                "probable_ist": ist(i.probable_utc),
                "overpass_count": i.overpass_count,
                "detections": len(i.detection_keys),
                "max_frp_mw": i.max_frp_mw,
                "reason": i.status_reason,
            }
            for i in incs
        ],
        "matched_detections": [
            {"key": d.key, "acq_ist": ist(d.acq_utc), "tier": d.confidence_tier, "frp_mw": d.frp_mw,
             "static": d.static_source, "match_distance_m": d.match_distance_m}
            for d in matched
        ],
        "nearest_unmatched": nearest,
        "_incidents": incs,
        "_matched": matched,
    }


def archive_wind(shape: SiteShape, start: date, end: date):
    """Open-Meteo archive hours for [start, end + 1 day] at the site centroid (cached)."""
    payload = wind.fetch_archive(shape.centroid_lat, shape.centroid_lon, start, end + timedelta(days=1),
                                 cache_dir=WIND_CACHE)
    return wind.parse_hourly(payload)


def enrich_incidents(shape: SiteShape, res: dict, start: date, end: date) -> list[tuple[Incident, list]]:
    """Smoke zone + receptors for every incident of a window (MVP §6.4, §6.5)."""
    if not res["_incidents"]:
        return []
    hours, grid = archive_wind(shape, start, end)
    site_receptors = receptors.load_receptors(shape.site_id)
    out = []
    for inc in res["_incidents"]:
        sel = pipeline.wind_hours_for(inc, res["_matched"], hours)
        out.append(pipeline.enrich(inc, shape, sel, grid, site_receptors, pipeline.status_time(inc)))
    return out


def smoke_summary(inc: Incident | None, inside: list) -> tuple[str, str, dict | None]:
    if inc is None or inc.smoke is None:
        return "—", "—", None
    z = inc.smoke
    if z.calm:
        text = f"calm: {z.length_km:g} km circle"
    else:
        names = list(dict.fromkeys(smoke.compass(t) for t in z.toward_deg))
        # Bearings wrap at 360°, so list the directions in time order instead of a min-max range.
        text = (f"toward {', '.join(names)}; {z.length_km:g} km; half-angle ≤ {z.half_angle_deg}°; "
                f"{len(z.wind_hours)} wind hours")
    kinds: dict[str, int] = {}
    for r in inside:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    detail = {"toward_deg": z.toward_deg, "half_angles_deg": z.half_angles_deg, "calm": z.calm,
              "length_km": z.length_km, "mean_speed_ms": z.mean_speed_ms, "wind_hours": len(z.wind_hours),
              "wind_point": [z.wind_point_lat, z.wind_point_lon], "receptors": len(inside),
              "receptor_kinds": kinds}
    return text, str(len(inside)), detail


def event_metrics(event: dict, res: dict, enriched: list[tuple[Incident, list]] | None = None) -> dict:
    """MVP §10.3. Detected = at least one PROBABLE incident in the window."""
    probable = [i for i in res["_incidents"] if i.status == "PROBABLE"]
    first = min(probable, key=lambda i: i.first_utc) if probable else None
    delta = None
    if first is not None:
        delta = (first.first_utc.astimezone(config.IST).date() - event["reported_start"]).days
    return {
        "event_id": event["event_id"],
        "site_id": event["site_id"],
        "reported_start": event["reported_start"].isoformat(),
        "window": f"{event['window_start']} to {event['window_end']}",
        "sources": event["archive_sources"],
        "detected": first is not None,
        "first_detection_ist": ist(first.first_utc) if first else None,
        "delta_days_from_reported_start": delta,
        "probable_reached_ist": ist(first.probable_utc) if first else None,
        "overpasses_with_detections": res["overpasses_with_detections"],
        "max_frp_mw": res["max_frp_mw"],
        **_smoke_fields(first, enriched),
    }


def _smoke_fields(first: Incident | None, enriched: list[tuple[Incident, list]] | None) -> dict:
    """Smoke zone and receptor count on the first PROBABLE incident (MVP §10.3)."""
    match = next(((i, r) for i, r in (enriched or []) if first is not None and i.incident_id == first.incident_id),
                 (None, []))
    text, count, detail = smoke_summary(*match)
    return {"smoke_zone": text, "receptor_count": count, "smoke_detail": detail}


# ---------------------------------------------------------------- guards and output


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=ROOT, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def freeze_state() -> tuple[bool, str]:
    if not FREEZE.exists():
        return False, "no data/config_freeze.yaml"
    frozen = yaml.safe_load(FREEZE.read_text(encoding="utf-8"))
    if frozen.get("config_hash") != config.config_hash():
        return False, f"config.py changed since freeze ({frozen.get('config_hash', '')[:12]})"
    return True, f"frozen {frozen.get('frozen_utc')} at {frozen.get('git_commit')}"


def do_freeze() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain", "src/lfw/config.py"], capture_output=True,
                           text=True, cwd=ROOT).stdout.strip()
    if dirty:
        log("config.py has uncommitted changes; commit it before freezing")
        return 2
    FREEZE.write_text(
        "# Config freeze before the first full backtest (MVP §10.4). Any later change to config.py\n"
        "# changes the hash; record it in README.md.\n"
        + yaml.safe_dump({"config_hash": config.config_hash(), "frozen_utc": utc_now_iso(),
                          "git_commit": git_commit()}, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    log(f"frozen: {config.config_hash()}")
    return 0


def fmt(v) -> str:
    return "—" if v is None else str(v)


def write_outputs(report: dict, stem: str) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n",
                                      encoding="utf-8", newline="\n")
    lines = [f"# Backtest results{' (DEV RUN — not for publication)' if report['dev'] else ''}", ""]
    lines += [
        f"- Generated: {report['generated_utc']} · git `{report['git_commit']}`",
        f"- Config hash: `{report['config_hash']}` · {report['freeze']}",
        f"- Outline check (`verified_by` in data/sites.yaml): {report['outlines_verified']}",
        "- Data: NASA FIRMS archive (standard processing). Detected = at least one PROBABLE incident in the window.",
        "",
        "## Documented fires",
        "",
        "| Event | Reported start | Sources | Detected | First detection (IST) | Δ days | PROBABLE reached (IST) | Overpasses with detections | Max FRP (MW) | Smoke zone | Receptors |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in report["events"]:
        lines.append(
            f"| {m['event_id']} | {m['reported_start']} | {', '.join(m['sources'])} | "
            f"{'yes' if m['detected'] else '**no (miss)**'} | {fmt(m['first_detection_ist'])} | "
            f"{fmt(m['delta_days_from_reported_start'])} | {fmt(m['probable_reached_ist'])} | "
            f"{m['overpasses_with_detections']} | {fmt(m['max_frp_mw'])} | {m['smoke_zone']} | {m['receptor_count']} |"
        )
    lines += [
        "",
        "## Alerts in windows with no reported fire",
        "",
        "Monsoon windows (15 Jul + 30 days, year before and after each event). No news report does not",
        "prove there was no fire, so these are not called false positives.",
        "",
        "| Site | Window (UTC days) | Matched detections | CANDIDATE incidents | PROBABLE incidents |",
        "|---|---|---|---|---|",
    ]
    for q in report["quiet_windows"]:
        statuses = [i["status"] for i in q["incidents"]]
        lines.append(f"| {q['site_id']} | {q['start']} to {q['end']} | {q['matched']} | "
                     f"{statuses.count('CANDIDATE')} | {statuses.count('PROBABLE')} |")
    lines += ["", f"Raw FIRMS CSVs: {len(report['fetches'])} calls, each cached with SHA-256 (see JSON `fetches`).", ""]
    (OUT / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def replay(event_id: str) -> int:
    """`make replay EVENT=...`: replay incidents (mode=replay) with smoke zone and receptors -> store."""
    from lfw.store import get_store

    ev = next((e for e in yaml.safe_load(EVENTS.read_text(encoding="utf-8")) if e["event_id"] == event_id), None)
    if ev is None:
        log(f"unknown event {event_id}")
        return 2
    key_secret = config.get_settings().firms_map_key
    key = key_secret.get_secret_value() if key_secret else ""
    site = next(s for s in load_sites() if s.site_id == ev["site_id"])
    shape = load_shapes([site])[site.site_id]
    a, b = ev["window_start"], ev["window_end"]
    raw, _ = fetch_window(key, ev["archive_sources"], query_bbox(shape), a, b)
    res = evaluate_window(shape, raw, a, b)
    store = get_store()
    store.put_detections(res["_matched"])
    for inc, inside in enrich_incidents(shape, res, a, b):
        prev = store.get_incident(inc.incident_id)
        if prev is not None:  # a re-run keeps a person's review of the replay incident
            (inc,) = incidents.apply_human_actions([inc], {prev.incident_id: prev})
        store.put_incident(inc)
        z = inc.smoke
        log(json.dumps({"event": "replay_incident", "incident_id": inc.incident_id, "status": inc.status,
                        "mode": inc.mode, "first_ist": ist(inc.first_utc), "status_reached_ist": ist(pipeline.status_time(inc)),
                        "overpasses": inc.overpass_count, "max_frp_mw": inc.max_frp_mw,
                        "smoke_toward_deg": z.toward_deg if z else None, "receptors_in_zone": len(inside)}))
    log(f"stored {len(res['_matched'])} detections and {len(res['_incidents'])} replay incidents")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", nargs="*", default=None)
    ap.add_argument("--dev", action="store_true", help="skip guards; write out/backtest_dev.*")
    ap.add_argument("--freeze", action="store_true", help="record the config freeze and exit")
    ap.add_argument("--replay", default=None, help="build replay incidents for one event into the store")
    args = ap.parse_args()

    if args.freeze:
        return do_freeze()
    if args.replay:
        return replay(args.replay)

    events = yaml.safe_load(EVENTS.read_text(encoding="utf-8"))
    if args.event:
        unknown = sorted(set(args.event) - {e["event_id"] for e in events})
        if unknown:
            log(f"unknown event ids: {unknown}")
            return 2
        events = [e for e in events if e["event_id"] in args.event]
    sites = {s.site_id: s for s in load_sites()}
    unverified = [e["site_id"] for e in events if not sites[e["site_id"]].verified_by]
    frozen, freeze_msg = freeze_state()
    log(f"config hash: {config.config_hash()} ({freeze_msg})")
    if not args.dev and (unverified or not frozen):
        log(f"refusing a publishable run: unverified outlines {unverified or 'none'}; freeze: {freeze_msg}")
        return 2

    key_secret = config.get_settings().firms_map_key
    key = key_secret.get_secret_value() if key_secret else ""
    if not key:
        log("FIRMS_MAP_KEY is empty in .env")
        return 2

    shapes = load_shapes([sites[e["site_id"]] for e in events])
    report = {
        "dev": args.dev,
        "generated_utc": utc_now_iso(),
        "git_commit": git_commit(),
        "config_hash": config.config_hash(),
        "freeze": freeze_msg,
        "outlines_verified": "; ".join(f"{e['site_id']}: {sites[e['site_id']].verified_by or 'NOT CHECKED'}"
                                       for e in events),
        "events": [],
        "event_windows": [],
        "quiet_windows": [],
        "fetches": [],
    }
    for ev in events:
        shape = shapes[ev["site_id"]]
        bbox = query_bbox(shape)
        windows = [("event", ev["window_start"], ev["window_end"])]
        windows += [("quiet", a, b) for a, b in quiet_windows(ev)]
        for kind, a, b in windows:
            log(f"[{ev['event_id']}] {kind} window {a}..{b}")
            raw, fetches = fetch_window(key, ev["archive_sources"], bbox, a, b)
            report["fetches"] += [{**f, "event_id": ev["event_id"], "window": kind} for f in fetches]
            res = evaluate_window(shape, raw, a, b)
            if kind == "event":
                m = event_metrics(ev, res, enrich_incidents(shape, res, a, b))
                report["events"].append(m)
                if not m["detected"]:
                    log(f"[{ev['event_id']}] MISS: no PROBABLE incident. Nearest raw detections:")
                    for n in res["nearest_unmatched"] + res["matched_detections"]:
                        log(f"    {n}")
            res.pop("_incidents")
            res.pop("_matched")
            res["event_id"] = ev["event_id"]
            (report["event_windows"] if kind == "event" else report["quiet_windows"]).append(res)

    stem = "backtest_dev" if args.dev else ("backtest_partial" if args.event else "backtest")
    write_outputs(report, stem)
    log(f"wrote out/{stem}.md and out/{stem}.json")
    print((OUT / f"{stem}.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

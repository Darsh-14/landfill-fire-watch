"""Read-only agent tools (MVP §7.2) and the DraftContext they are built from.

Every value here comes from the store, data/ files or deterministic code. The tools never write.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from lfw import pipeline
from lfw import receptors as rc
from lfw.agent.contract import DraftContext, FactsUsed
from lfw.logjson import log_json
from lfw.models import Incident
from lfw.sites import load_sites
from lfw.smoke import SCREENING_NOTE, compass
from lfw.store import Store
from lfw.timeutil import ist_str

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "data" / "rules.yaml"
MAX_RECEPTORS_LISTED = 15  # nearest receptors given to the model; the full list stays in the context

# Fixed limits text (MVP §9). The dashboard shows the same five lines (tests check they match).
LIMITS = [
    "Detects surface fires only. Fires that smoulder underground can be missed.",
    "Pixel size is about 375 m (VIIRS) to 1 km or more (MODIS). A hotspot can come from a nearby heat source.",
    "Satellites pass a few times a day. Cloud and thick smoke can block detection.",
    "A detection is not a confirmation. A person must check.",
    "The smoke zone is a screening sector from wind direction. It is not a pollution forecast.",
]


def verified_rules(path: Path = RULES) -> dict[str, dict]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {e["key"]: e for e in entries if e.get("verified") is True}


def data_age_sentence(inc: Incident, now: datetime) -> str:
    if inc.mode == "replay":
        latest = pipeline.status_time(inc)
        return f"Data age: REPLAY of historical data; the latest satellite detection used is from {ist_str(latest)}."
    hours = (now - inc.last_utc).total_seconds() / 3600
    return (f"Data age: the latest satellite detection used is from {ist_str(inc.last_utc)}, "
            f"{hours:.0f} h before this draft.")


def build_context(store: Store, incident_id: str, now: datetime | None = None,
                  hindi_enabled: bool = False) -> DraftContext:
    now = now or datetime.now(UTC)
    inc = store.get_incident(incident_id)
    if inc is None:
        raise KeyError(f"unknown incident {incident_id}")
    site = next(s for s in load_sites() if s.site_id == inc.site_id)
    site_receptors = rc.load_receptors(inc.site_id)
    by_id = {r.receptor_id: r for r in site_receptors}
    in_zone = sorted((by_id[i] for i in inc.receptor_ids if i in by_id), key=lambda r: (r.distance_km, r.receptor_id))
    toward = inc.smoke.toward_deg if inc.smoke else []
    return DraftContext(
        incident_id=inc.incident_id,
        mode=inc.mode,
        status=inc.status,
        site_name=site.name,
        city=site.city,
        state=site.state,
        facts=FactsUsed(overpass_count=inc.overpass_count, first_detected_ist=ist_str(inc.first_utc),
                        smoke_toward_deg=toward, status=inc.status),
        max_frp_mw=inc.max_frp_mw,
        toward_compass=list(dict.fromkeys(compass(t) for t in toward)),
        smoke_length_km=inc.smoke.length_km if inc.smoke else None,
        calm=inc.smoke.calm if inc.smoke else None,
        receptors_in_zone=in_zone,
        site_receptors=site_receptors,
        verified_rule_keys=sorted(verified_rules()),
        screening_sentence=SCREENING_NOTE,
        data_age_sentence=data_age_sentence(inc, now),
        limits=LIMITS,
        hindi_enabled=hindi_enabled,
    )


# ---- tool payloads (plain functions, so the fake model and tests can call them too)


def incident_payload(ctx: DraftContext) -> dict:
    return {
        "incident_id": ctx.incident_id, "mode": ctx.mode, "status": ctx.status,
        "site": {"name": ctx.site_name, "city": ctx.city, "state": ctx.state},
        "first_detected_ist": ctx.facts.first_detected_ist, "overpass_count": ctx.facts.overpass_count,
        "max_frp_mw": ctx.max_frp_mw, "facts_used": ctx.facts.model_dump(),
        "screening_sentence": ctx.screening_sentence, "data_age_sentence": ctx.data_age_sentence,
        "hindi_enabled": ctx.hindi_enabled,
        "replay_prefix_required": ctx.mode == "replay",
    }


def smoke_payload(ctx: DraftContext) -> dict:
    return {"toward_deg": ctx.facts.smoke_toward_deg, "toward_compass": ctx.toward_compass,
            "length_km": ctx.smoke_length_km, "calm": ctx.calm, "note": ctx.screening_sentence}


def receptors_payload(ctx: DraftContext) -> dict:
    return {
        "total_in_zone": len(ctx.receptors_in_zone),
        "nearest": [{"receptor_id": r.receptor_id, "name": rc.display_name(r), "kind": r.kind,
                     "distance_km": r.distance_km} for r in ctx.receptors_in_zone[:MAX_RECEPTORS_LISTED]],
    }


def rule_payload(ctx: DraftContext, rule_key: str) -> dict:
    rules = verified_rules()
    if rule_key not in rules:
        return {"error": f"rule '{rule_key}' is not verified; do not cite it", "verified_rule_keys": sorted(rules)}
    r = rules[rule_key]
    return {"key": r["key"], "text": r["text"], "source_id": r["source_id"], "page": r.get("page")}


def limits_payload(ctx: DraftContext) -> dict:
    return {"limits": ctx.limits}


def call_logged(name: str, ctx: DraftContext, fn, *args) -> dict:
    out = fn(ctx, *args)
    log_json("agent_tool_call", incident_id=ctx.incident_id, tool=name, input=list(args) or None,
             output_keys=sorted(out))
    return out


def strands_tools(ctx: DraftContext) -> list:
    """The five read-only tools as Strands @tool functions bound to one incident."""
    from strands import tool

    def _check(incident_id: str) -> None:
        if incident_id != ctx.incident_id:
            raise ValueError(f"this agent run is for {ctx.incident_id}, not {incident_id}")

    @tool
    def get_incident(incident_id: str) -> str:
        """Site, status, mode, first detection time (IST), overpass count, max FRP, facts_used, and the exact
        screening_sentence and data_age_sentence that the official alert must contain."""
        _check(incident_id)
        return json.dumps(incident_payload(ctx), ensure_ascii=False)

    @tool
    def get_smoke_zone(incident_id: str) -> str:
        """Smoke screening sector: toward directions (degrees and compass), length, calm flag."""
        _check(incident_id)
        return json.dumps(smoke_payload(ctx))

    @tool
    def list_receptors(incident_id: str) -> str:
        """Schools, colleges, kindergartens, hospitals and clinics inside the screening sector, nearest first:
        receptor_id, name, kind, distance_km. Only these places may be named."""
        _check(incident_id)
        return json.dumps(receptors_payload(ctx), ensure_ascii=False)

    @tool
    def get_rule(rule_key: str) -> str:
        """A verified rule quote with source and page. Unverified rules return an error and must not be cited."""
        return json.dumps(rule_payload(ctx, rule_key), ensure_ascii=False)

    @tool
    def get_limits() -> str:
        """The fixed list of system limits to mention in the official alert."""
        return json.dumps(limits_payload(ctx))

    return [get_incident, get_smoke_zone, list_receptors, get_rule, get_limits]

"""A fake drafting model for local development and tests (no Ollama, no AWS).

It reads the same tool outputs a real model would (and logs those tool calls), writes a draft in its
own words, and can inject named defects so the validator, the retry and the fallback can be shown
and tested. Scenarios:
  good              valid draft on the first attempt
  bad-then-good     first draft invents a school; the retry is valid (default for `make draft`)
  always-bad        both attempts invalid -> fixed template is used
"""

from __future__ import annotations

import json

from lfw.agent import tools as T
from lfw.agent.contract import DraftContext

INVENTED_SCHOOL = "Sunrise Valley Public School"  # does not exist in the OSM data: must be rejected


def _good(ctx: DraftContext) -> dict:
    inc = T.call_logged("get_incident", ctx, T.incident_payload)
    sm = T.call_logged("get_smoke_zone", ctx, T.smoke_payload)
    rec = T.call_logged("list_receptors", ctx, T.receptors_payload)
    T.call_logged("get_limits", ctx, T.limits_payload)
    pre = "[REPLAY] " if inc["replay_prefix_required"] else ""
    near = rec["nearest"][:5]
    dirs = ", ".join(sm["toward_compass"]) or "nearby areas"
    places = "; ".join(f"{r['name']} ({r['kind']}, {r['distance_km']} km)" for r in near) or "none"
    official = (
        f"{pre}Satellite hotspot and possible fire at {inc['site']['name']} landfill, {inc['site']['city']}. "
        f"First detected {inc['first_detected_ist']}; {inc['overpass_count']} overpasses with detections; "
        f"code status {inc['status']}. Smoke screening direction: toward {dirs}. "
        f"Nearest places in the sector: {places} ({rec['total_in_zone']} in total). "
        f"{inc['screening_sentence']} {inc['data_age_sentence']} "
        "A person must check the site before any public statement."
    )
    resident = (f"{pre}Possible fire at the {inc['site']['name']} landfill. Smoke may move toward {dirs}. "
                "Please keep windows closed, avoid outdoor activity near the site, and look after children, "
                "older people and people with breathing illness.")
    hi = ""
    if inc["hindi_enabled"]:
        hi = f"{pre}{inc['site']['name']} लैंडफिल पर संभावित आग। खिड़कियाँ बंद रखें।"  # TODO(verify)
    return {
        "resident_advisory_en": resident,
        "resident_advisory_hi": hi,
        "official_alert_en": official,
        "rule_keys": [],
        "receptor_ids": [r["receptor_id"] for r in near],
        "facts_used": inc["facts_used"],
    }


DEFECTS = {
    "invented_school": lambda d, ctx: {**d, "official_alert_en": d["official_alert_en"].replace(
        "Nearest places in the sector:", f"Nearest places in the sector: {INVENTED_SCHOOL} (school, 0.8 km);")},
    "confirmed": lambda d, ctx: {**d, "resident_advisory_en": d["resident_advisory_en"] + " The fire is confirmed."},
    "no_replay_prefix": lambda d, ctx: {**d, "resident_advisory_en": d["resident_advisory_en"].replace("[REPLAY] ", "", 1)},
    "unverified_rule": lambda d, ctx: {**d, "rule_keys": ["swm2026_dumpsite_fire_prevention"]},
    "wrong_facts": lambda d, ctx: {**d, "facts_used": {**d["facts_used"], "overpass_count": d["facts_used"]["overpass_count"] + 1}},
    "health_claim": lambda d, ctx: {**d, "resident_advisory_en": d["resident_advisory_en"] + " Air has toxic levels."},
    "not_json": lambda d, ctx: "Sure! Here is the draft you asked for.",
}

SCENARIOS = {
    "good": [[]],
    "bad-then-good": [["invented_school"], []],
    "always-bad": [["invented_school", "confirmed"], ["no_replay_prefix"]],
}


class FakeDrafter:
    def __init__(self, scenario: str = "bad-then-good") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown fake scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
        self.scenario = scenario
        self.name = f"fake:{scenario}"
        self._attempt = 0

    def _produce(self, ctx: DraftContext) -> str:
        steps = SCENARIOS[self.scenario]
        defects = steps[min(self._attempt, len(steps) - 1)]
        self._attempt += 1
        draft: dict | str = _good(ctx)
        for name in defects:
            draft = DEFECTS[name](draft, ctx) if isinstance(draft, dict) else draft
        return draft if isinstance(draft, str) else json.dumps(draft, ensure_ascii=False)

    def first(self, ctx: DraftContext) -> str:
        return self._produce(ctx)

    def retry(self, ctx: DraftContext, errors: list[str]) -> str:
        return self._produce(ctx)


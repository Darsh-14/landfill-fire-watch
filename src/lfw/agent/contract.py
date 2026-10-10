"""Output contract (MVP §7.3) and the validator with all 11 checks (MVP §7.4).

The validator is the gate between model text and a person: a draft that fails any check is never
shown as "validated". It compares the draft only with facts that code computed (DraftContext).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from lfw.models import Receptor

# Required wording (MVP §7.4 checks 7 and 9). Hindi equivalents are TODO(verify) by a Hindi speaker.
REQUIRED_PHRASES_EN = ("possible fire", "satellite hotspot")
REQUIRED_PHRASES_HI = ("संभावित आग", "उपग्रह हॉटस्पॉट")  # TODO(verify)
BANNED_HEALTH = (
    re.compile(r"\btoxic\s+levels?\b", re.I),
    re.compile(r"\bdangerous\s+AQI\b", re.I),
    re.compile(r"\bAQI\b\D{0,20}\d", re.I),  # a specific AQI number
    re.compile(r"\d+\s*AQI\b", re.I),
)
CONFIRMED = re.compile(r"\bconfirmed\b", re.I)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
REPLAY_PREFIX = "[REPLAY]"

# A place mention: up to 6 capitalised words followed by a receptor-type word (check 4).
PLACE_WORDS = (
    "School", "Schools", "College", "Hospital", "Clinic", "Kindergarten", "Vidyalaya", "Vidyalayam",
    "Academy", "Institute", "University", "Polytechnic", "Nursing Home", "Medical Centre",
    "Medical Center", "Health Centre", "Health Center", "Anganwadi", "Dispensary",
)
PLACE_MENTION = re.compile(
    r"((?:[A-Z][\w.'&-]*\s+){1,6}(?:" + "|".join(re.escape(w) for w in PLACE_WORDS) + r"))\b"
)


class FactsUsed(BaseModel):
    overpass_count: int
    first_detected_ist: str
    smoke_toward_deg: list[int]
    status: str


class DraftBundle(BaseModel):
    resident_advisory_en: str = Field(max_length=700)
    resident_advisory_hi: str = Field(max_length=900)
    official_alert_en: str = Field(max_length=1800)
    rule_keys: list[str]
    receptor_ids: list[str]
    facts_used: FactsUsed


class DraftContext(BaseModel):
    """Everything code computed for one incident. Built by agent/tools.py, never by the model."""

    incident_id: str
    mode: str
    status: str
    site_name: str
    city: str
    state: str
    facts: FactsUsed
    max_frp_mw: float | None
    toward_compass: list[str]
    smoke_length_km: float | None
    calm: bool | None
    receptors_in_zone: list[Receptor]  # full list, nearest first
    site_receptors: list[Receptor]  # everything cached within 12 km (for the name check)
    verified_rule_keys: list[str]
    screening_sentence: str
    data_age_sentence: str
    limits: list[str]
    hindi_enabled: bool


class CheckResult(BaseModel):
    check: int
    name: str
    passed: bool | None  # None = skipped (e.g. Hindi disabled)
    detail: str = ""


class ValidationReport(BaseModel):
    passed: bool
    checks: list[CheckResult]

    def errors(self) -> list[str]:
        return [f"check {c.check} ({c.name}): {c.detail}" for c in self.checks if c.passed is False]


def _texts(d: DraftBundle, ctx: DraftContext) -> dict[str, str]:
    t = {"resident_advisory_en": d.resident_advisory_en, "official_alert_en": d.official_alert_en}
    if ctx.hindi_enabled:
        t["resident_advisory_hi"] = d.resident_advisory_hi
    return t


def validate(raw: str | dict, ctx: DraftContext) -> tuple[DraftBundle | None, ValidationReport]:
    checks: list[CheckResult] = []

    def add(n: int, name: str, ok: bool | None, detail: str = "") -> None:
        checks.append(CheckResult(check=n, name=name, passed=ok, detail=detail))

    # 1. JSON parses into DraftBundle
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        draft = DraftBundle.model_validate(data)
        add(1, "parses into DraftBundle", True)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        add(1, "parses into DraftBundle", False, str(exc).splitlines()[0][:300])
        return None, ValidationReport(passed=False, checks=checks)

    texts = _texts(draft, ctx)
    zone_ids = {r.receptor_id for r in ctx.receptors_in_zone}

    # 2. every rule_key is in rules.yaml with verified: true
    bad_rules = [k for k in draft.rule_keys if k not in ctx.verified_rule_keys]
    add(2, "rule keys verified", not bad_rules, f"not verified or unknown: {bad_rules}" if bad_rules else "")

    # 3. every receptor_id is in the incident's receptor list
    bad_ids = [r for r in draft.receptor_ids if r not in zone_ids]
    add(3, "receptor ids in incident list", not bad_ids, f"not in the smoke zone list: {bad_ids}" if bad_ids else "")

    # 4. every receptor name in any text belongs to a listed receptor_id
    listed = [r for r in ctx.receptors_in_zone if r.receptor_id in set(draft.receptor_ids)]
    listed_names = [r.name.lower() for r in listed if r.name]
    listed_kinds_unnamed = {r.kind for r in listed if not r.name}
    problems = []
    for field, text in texts.items():
        listed_ids = {x.receptor_id for x in listed}
        for r in ctx.site_receptors:  # a real nearby place mentioned but not listed
            # Multi-word names only, so generic words ("clinic") never count as a place mention.
            if (r.name and " " in r.name.strip() and len(r.name) >= 8 and r.name.lower() in text.lower()
                    and r.receptor_id not in listed_ids):
                problems.append(f"{field}: '{r.name}' is not a listed receptor")
        for m in PLACE_MENTION.finditer(text):  # a place that is not in the data at all
            mention = m.group(1).strip()
            low = mention.lower()
            if low.startswith("unnamed "):
                if not any(k in low for k in listed_kinds_unnamed):
                    problems.append(f"{field}: '{mention}' has no unnamed receptor of that kind listed")
                continue
            if not any(low in n or n in low for n in listed_names):
                problems.append(f"{field}: '{mention}' does not match any listed receptor name")
    add(4, "receptor names belong to listed ids", not problems, "; ".join(dict.fromkeys(problems))[:500])

    # 5. facts_used equals the computed values exactly
    diff = {k: (v, getattr(ctx.facts, k)) for k, v in draft.facts_used.model_dump().items()
            if v != getattr(ctx.facts, k)}
    add(5, "facts_used equals computed facts", not diff,
        "; ".join(f"{k}: draft {a!r} != computed {b!r}" for k, (a, b) in diff.items()))

    # 6. "confirmed" only if status is CONFIRMED
    if ctx.status != "CONFIRMED":
        hits = [f for f, t in texts.items() if CONFIRMED.search(t)]
        add(6, "'confirmed' only when CONFIRMED", not hits, f"'confirmed' used in {hits} but status is {ctx.status}" if hits else "")
    else:
        add(6, "'confirmed' only when CONFIRMED", True)

    # 7. each text contains "possible fire" or "satellite hotspot"
    missing = []
    for f, t in texts.items():
        phrases = REQUIRED_PHRASES_EN + (REQUIRED_PHRASES_HI if f.endswith("_hi") else ())
        if not any(p in t.lower() if p.isascii() else p in t for p in phrases):
            missing.append(f)
    add(7, "says 'possible fire' or 'satellite hotspot'", not missing, f"missing in {missing}" if missing else "")

    # 8. official alert has the screening-sector sentence and the data-age sentence
    lacks = [n for n, s in (("screening-sector sentence", ctx.screening_sentence),
                            ("data-age sentence", ctx.data_age_sentence)) if s not in draft.official_alert_en]
    add(8, "official alert has screening + data-age sentences", not lacks, f"missing {lacks}" if lacks else "")

    # 9. no health claims (MVP: no AQI tool, so these phrases are banned)
    health = [f"{f}: '{m.group(0)}'" for f, t in texts.items() for rx in BANNED_HEALTH for m in rx.finditer(t)]
    add(9, "no health claims (AQI / toxic levels)", not health, "; ".join(health))

    # 10. the Hindi text contains Devanagari
    if ctx.hindi_enabled:
        add(10, "Hindi text is Devanagari", bool(DEVANAGARI.search(draft.resident_advisory_hi)),
            "" if DEVANAGARI.search(draft.resident_advisory_hi) else "no Devanagari characters")
    else:
        add(10, "Hindi text is Devanagari", None, "skipped: Hindi disabled (no reviewer, MVP A4)")

    # 11. replay incidents: every text starts with [REPLAY]
    if ctx.mode == "replay":
        no_prefix = [f for f, t in texts.items() if not t.lstrip().startswith(REPLAY_PREFIX)]
        add(11, "replay texts start with [REPLAY]", not no_prefix, f"missing prefix in {no_prefix}" if no_prefix else "")
    else:
        add(11, "replay texts start with [REPLAY]", True, "live incident")

    return draft, ValidationReport(passed=all(c.passed is not False for c in checks), checks=checks)

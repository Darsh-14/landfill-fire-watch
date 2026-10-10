"""Fixed templates filled with computed facts (MVP §7.4): used when the model fails twice.

The English templates are the project's own wording. The Hindi template is TODO(verify): it has not
been reviewed by a Hindi speaker, so it ships switched off (Settings.hindi_enabled = False, MVP A4).
"""

from __future__ import annotations

from lfw import receptors as rc
from lfw.agent.contract import DraftBundle, DraftContext

MAX_RECEPTORS_IN_ALERT = 8


def _prefix(ctx: DraftContext) -> str:
    return "[REPLAY] " if ctx.mode == "replay" else ""


def _direction(ctx: DraftContext) -> str:
    if ctx.calm:
        return "in all directions close to the site (light wind)"
    if not ctx.toward_compass:
        return "in an unknown direction (no wind data)"
    return "toward " + ", ".join(ctx.toward_compass)


def resident_en(ctx: DraftContext) -> str:
    return (f"{_prefix(ctx)}Possible fire at the {ctx.site_name} landfill, {ctx.city}. A satellite hotspot was "
            f"first seen on {ctx.facts.first_detected_ist}. Smoke may drift {_direction(ctx)}. If you live nearby: "
            "keep windows and doors closed, avoid outdoor activity near the site, and take care of children, "
            "older people and anyone with breathing illness. Follow instructions from local officials.")


def resident_hi(ctx: DraftContext) -> str:
    # TODO(verify): Hindi wording not reviewed by a Hindi speaker. Disabled unless hindi_enabled.
    if not ctx.hindi_enabled:
        return ""
    dirs = ", ".join(ctx.toward_compass) if ctx.toward_compass else "-"
    return (f"{_prefix(ctx)}{ctx.site_name} लैंडफिल ({ctx.city}) पर संभावित आग। उपग्रह हॉटस्पॉट पहली बार "
            f"{ctx.facts.first_detected_ist} को देखा गया। धुआँ {dirs} दिशा की ओर जा सकता है। खिड़कियाँ और दरवाज़े बंद "
            "रखें, स्थल के पास बाहर की गतिविधि से बचें, और बच्चों, बुज़ुर्गों तथा साँस की बीमारी वाले लोगों का ध्यान रखें।")


def _max_len(field: str) -> int:
    """max_length of a DraftBundle text field (the contract is the single source of the limits)."""
    return next(m.max_length for m in DraftBundle.model_fields[field].metadata if hasattr(m, "max_length"))


def _fit(text: str, field: str) -> str:
    """Keep a template text within its contract limit (cut at a word boundary, never mid-word)."""
    limit = _max_len(field)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def official_en(ctx: DraftContext, n_receptors: int = MAX_RECEPTORS_IN_ALERT) -> str:
    listed = ctx.receptors_in_zone[:n_receptors]
    places = "; ".join(f"{rc.display_name(r)} ({r.kind}, {r.distance_km:g} km)" for r in listed) or "none in the sector"
    more = len(ctx.receptors_in_zone) - len(listed)
    frp = f"{ctx.max_frp_mw:g} MW" if ctx.max_frp_mw is not None else "not available"
    rules = ", ".join(ctx.verified_rule_keys) if ctx.verified_rule_keys else "none (no rule verified yet)"
    parts = [
        f"{_prefix(ctx)}Possible fire (satellite hotspot) at {ctx.site_name} landfill, {ctx.city}, {ctx.state}.",
        f"Status computed by rules: {ctx.status}. First detection: {ctx.facts.first_detected_ist}. "
        f"Overpasses with detections: {ctx.facts.overpass_count}. Max FRP: {frp}.",
        f"Smoke screening direction: {_direction(ctx)}"
        + (f" ({', '.join(str(t) for t in ctx.facts.smoke_toward_deg)} deg), up to {ctx.smoke_length_km:g} km."
           if ctx.facts.smoke_toward_deg and not ctx.calm else "."),
        f"Places in the sector, nearest first: {places}" + (f"; and {more} more." if more > 0 else "."),
        f"Rule citations: {rules}.",
        ctx.screening_sentence,
        ctx.data_age_sentence,
        "Limits: surface fires only; pixel 375 m to 1 km or more; cloud and smoke can block detection; "
        "a person must check on site.",
    ]
    return "\n".join(parts)


def build(ctx: DraftContext) -> DraftBundle:
    """Always returns a bundle within the contract limits: fewer receptors are listed when long
    names would push the official alert past its maximum length."""
    limit = _max_len("official_alert_en")
    n = min(MAX_RECEPTORS_IN_ALERT, len(ctx.receptors_in_zone))
    while n > 0 and len(official_en(ctx, n)) > limit:
        n -= 1
    listed = ctx.receptors_in_zone[:n]
    return DraftBundle(
        resident_advisory_en=_fit(resident_en(ctx), "resident_advisory_en"),
        resident_advisory_hi=_fit(resident_hi(ctx), "resident_advisory_hi"),
        official_alert_en=_fit(official_en(ctx, n), "official_alert_en"),
        rule_keys=list(ctx.verified_rule_keys),
        receptor_ids=[r.receptor_id for r in listed],
        facts_used=ctx.facts,
    )

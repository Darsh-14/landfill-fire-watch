"""Validator: one test per MVP §7.4 check, plus retry and fallback behaviour."""

import json

import pytest

from lfw.agent import fallback
from lfw.agent.contract import DraftContext, FactsUsed, validate
from lfw.agent.fake import INVENTED_SCHOOL, FakeDrafter
from lfw.agent.run import run_draft
from lfw.agent.tools import LIMITS
from lfw.models import Receptor
from lfw.smoke import SCREENING_NOTE

R1 = Receptor(receptor_id="osm:node/1", name="Govt Higher Secondary School Kakkanad", kind="school",
              lat=10.0, lon=76.3, distance_km=1.2)
R2 = Receptor(receptor_id="osm:way/2", name=None, kind="hospital", lat=10.0, lon=76.31, distance_km=2.5)
R_OUT = Receptor(receptor_id="osm:node/9", name="Lakeside Medical Centre", kind="clinic",
                 lat=10.2, lon=76.5, distance_km=9.0)  # within 12 km but not in the smoke zone


def make_ctx(**over) -> DraftContext:
    base = dict(
        incident_id="brahmapuram-kochi-20230302T1635", mode="replay", status="PROBABLE",
        site_name="Brahmapuram", city="Kochi", state="Kerala",
        facts=FactsUsed(overpass_count=12, first_detected_ist="2023-03-02 22:05 IST",
                        smoke_toward_deg=[0, 284, 274], status="PROBABLE"),
        max_frp_mw=27.1, toward_compass=["N", "WNW", "W"], smoke_length_km=10.0, calm=False,
        receptors_in_zone=[R1, R2], site_receptors=[R1, R2, R_OUT],
        verified_rule_keys=["rule_ok"], screening_sentence=SCREENING_NOTE,
        data_age_sentence="Data age: REPLAY of historical data; the latest satellite detection used is from 2023-03-02 22:05 IST.",
        limits=LIMITS, hindi_enabled=False,
    )
    base.update(over)
    return DraftContext(**base)


def good(ctx: DraftContext) -> dict:
    return fallback.build(ctx).model_dump()


def check(report, n):
    return next(c for c in report.checks if c.check == n)


def test_good_template_passes_all_checks():
    ctx = make_ctx()
    _, rep = validate(good(ctx), ctx)
    assert rep.passed, rep.errors()


# 1
def test_check1_not_json_is_rejected():
    _, rep = validate("Sure! Here is your draft.", make_ctx())
    assert not rep.passed and check(rep, 1).passed is False


def test_check1_too_long_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["resident_advisory_en"] = "[REPLAY] possible fire " + "x" * 700
    _, rep = validate(d, ctx)
    assert check(rep, 1).passed is False


# 2
def test_check2_unverified_rule_key_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["rule_keys"] = ["swm2026_dumpsite_fire_prevention"]
    _, rep = validate(d, ctx)
    assert check(rep, 2).passed is False and not rep.passed


# 3
def test_check3_receptor_id_outside_zone_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["receptor_ids"].append("osm:node/9")
    _, rep = validate(d, ctx)
    assert check(rep, 3).passed is False


# 4
def test_check4_invented_school_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["official_alert_en"] = d["official_alert_en"].replace("Places in the sector, nearest first:",
                                                            f"Places in the sector, nearest first: {INVENTED_SCHOOL} (school, 0.8 km);")
    _, rep = validate(d, ctx)
    assert check(rep, 4).passed is False and INVENTED_SCHOOL in check(rep, 4).detail


def test_check4_real_but_unlisted_place_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["resident_advisory_en"] += " Lakeside Medical Centre is open."
    _, rep = validate(d, ctx)
    assert check(rep, 4).passed is False


# 5
def test_check5_facts_must_match_exactly():
    ctx = make_ctx()
    d = good(ctx)
    d["facts_used"]["first_detected_ist"] = "2023-03-02 22:06 IST"
    _, rep = validate(d, ctx)
    assert check(rep, 5).passed is False


# 6
def test_check6_confirmed_with_probable_status_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["resident_advisory_en"] += " The fire is confirmed."
    _, rep = validate(d, ctx)
    assert check(rep, 6).passed is False


def test_check6_confirmed_allowed_when_status_confirmed():
    ctx = make_ctx(status="CONFIRMED", facts=FactsUsed(overpass_count=12, first_detected_ist="2023-03-02 22:05 IST",
                                                         smoke_toward_deg=[0, 284, 274], status="CONFIRMED"))
    d = good(ctx)
    d["resident_advisory_en"] += " Confirmed by the duty officer."
    _, rep = validate(d, ctx)
    assert check(rep, 6).passed is True


# 7
def test_check7_required_wording():
    ctx = make_ctx()
    d = good(ctx)
    d["resident_advisory_en"] = "[REPLAY] There is smoke near the landfill. Keep windows closed."
    _, rep = validate(d, ctx)
    assert check(rep, 7).passed is False


# 8
def test_check8_official_alert_needs_both_sentences():
    ctx = make_ctx()
    d = good(ctx)
    d["official_alert_en"] = d["official_alert_en"].replace(ctx.data_age_sentence, "")
    _, rep = validate(d, ctx)
    assert check(rep, 8).passed is False


# 9
@pytest.mark.parametrize("claim", ["Air has toxic levels.", "AQI is 412 today.", "There is dangerous AQI."])
def test_check9_health_claims_are_banned(claim):
    ctx = make_ctx()
    d = good(ctx)
    d["resident_advisory_en"] += " " + claim
    _, rep = validate(d, ctx)
    assert check(rep, 9).passed is False


# 10
def test_check10_hindi_needs_devanagari_when_enabled():
    ctx = make_ctx(hindi_enabled=True)
    d = good(ctx)
    assert check(validate(d, ctx)[1], 10).passed is True
    d["resident_advisory_hi"] = "[REPLAY] possible fire (transliterated, no Devanagari)"
    assert check(validate(d, ctx)[1], 10).passed is False


def test_check10_skipped_when_hindi_disabled():
    ctx = make_ctx()
    assert check(validate(good(ctx), ctx)[1], 10).passed is None


# 11
def test_check11_missing_replay_prefix_is_rejected():
    ctx = make_ctx()
    d = good(ctx)
    d["official_alert_en"] = d["official_alert_en"].replace("[REPLAY] ", "", 1)
    _, rep = validate(d, ctx)
    assert check(rep, 11).passed is False


def test_check11_live_incident_needs_no_prefix():
    ctx = make_ctx(mode="live", data_age_sentence="Data age: the latest satellite detection used is from 2026-10-10 13:00 IST, 1 h before this draft.")
    _, rep = validate(good(ctx), ctx)
    assert rep.passed and not good(ctx)["official_alert_en"].startswith("[REPLAY]")


# retry + fallback
def test_bad_then_good_uses_the_retry():
    ctx = make_ctx()
    rec = run_draft(ctx, FakeDrafter("bad-then-good"))
    assert [a["passed"] for a in rec["attempts"]] == [False, True]
    assert rec["validated"] and not rec["template_used"]


def test_two_failures_fall_back_to_the_template():
    ctx = make_ctx()
    rec = run_draft(ctx, FakeDrafter("always-bad"))
    assert [a["source"] for a in rec["attempts"]] == ["fake:always-bad", "fake:always-bad", "template"]
    assert rec["template_used"] and rec["validated"]


def test_model_exception_counts_as_failed_attempt():
    class Broken:
        name = "broken"

        def first(self, ctx):
            raise TimeoutError("bedrock timeout")

        def retry(self, ctx, errors):
            raise TimeoutError("bedrock timeout")

    rec = run_draft(make_ctx(), Broken())
    assert rec["template_used"] and rec["validated"] and len(rec["attempts"]) == 3


def test_hindi_template_is_devanagari_and_valid_when_enabled():
    ctx = make_ctx(hindi_enabled=True)
    d = fallback.build(ctx)
    assert d.resident_advisory_hi.startswith("[REPLAY]") and validate(d.model_dump(), ctx)[1].passed


def test_validator_accepts_json_string():
    ctx = make_ctx()
    assert validate(json.dumps(good(ctx)), ctx)[1].passed


def test_strands_tools_are_the_five_read_only_tools():
    pytest.importorskip("strands")
    from lfw.agent.tools import strands_tools

    ctx = make_ctx()
    tools = strands_tools(ctx)
    names = sorted(t.tool_name for t in tools)
    assert names == ["get_incident", "get_limits", "get_rule", "get_smoke_zone", "list_receptors"]
    payload = json.loads(next(t for t in tools if t.tool_name == "get_rule")("swm2026_dumpsite_fire_prevention"))
    assert "error" in payload  # unverified rules are refused by the tool itself

"""Run the drafting agent on one incident: draft -> validate -> retry once -> fallback (MVP §7.4).

Usage (make draft INCIDENT=<id>):
  python -m lfw.agent.run <incident_id> [--model fake|bedrock] [--scenario bad-then-good] [--no-store]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from typing import Protocol

from lfw.agent import fallback
from lfw.agent.contract import DraftBundle, DraftContext, ValidationReport, validate
from lfw.agent.prompts import SYSTEM_PROMPT, retry_prompt, user_prompt
from lfw.agent.tools import build_context, strands_tools
from lfw.config import get_settings
from lfw.logjson import log_json
from lfw.store import Store, get_store
from lfw.timeutil import utc_iso


class Drafter(Protocol):
    name: str

    def first(self, ctx: DraftContext) -> str: ...
    def retry(self, ctx: DraftContext, errors: list[str]) -> str: ...


class StrandsBedrockDrafter:
    """Strands Agent on Amazon Bedrock with the five read-only tools and structured output."""

    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
        if not self.model_id:
            raise RuntimeError("BEDROCK_MODEL_ID is not set")
        self.region = region or os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION")
        self.name = f"bedrock:{self.model_id}"
        self._agent = None

    def _make_agent(self, ctx: DraftContext):
        from strands import Agent
        from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
        from strands.models import BedrockModel

        incident_id = ctx.incident_id

        class ToolLog(HookProvider):
            def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
                registry.add_callback(AfterToolCallEvent, self.after)

            def after(self, event: AfterToolCallEvent) -> None:
                log_json("agent_tool_call", incident_id=incident_id, tool=event.tool_use.get("name"),
                         input=event.tool_use.get("input"), duration_s=getattr(event, "duration", None),
                         error=str(event.exception) if event.exception else None)

        # streaming=False: the Converse call needs only bedrock:InvokeModel (least privilege).
        model = BedrockModel(model_id=self.model_id, region_name=self.region, temperature=0.2,
                             max_tokens=2500, streaming=False)
        return Agent(model=model, tools=strands_tools(ctx), system_prompt=SYSTEM_PROMPT,
                     hooks=[ToolLog()], callback_handler=None)

    def _ask(self, prompt: str) -> str:
        from strands.types.exceptions import StructuredOutputException

        try:
            result = self._agent(prompt, structured_output_model=DraftBundle)
            out = result.structured_output
            return out.model_dump_json() if out is not None else json.dumps({"_error": "no structured output"})
        except StructuredOutputException as exc:
            return json.dumps({"_error": f"structured output failed: {exc}"[:500]})

    def first(self, ctx: DraftContext) -> str:
        self._agent = self._make_agent(ctx)
        return self._ask(user_prompt(ctx))

    def retry(self, ctx: DraftContext, errors: list[str]) -> str:
        return self._ask(retry_prompt(errors))


def make_drafter(kind: str | None = None, scenario: str | None = None) -> Drafter:
    s = get_settings()
    kind = kind or s.draft_model
    if kind == "bedrock":
        return StrandsBedrockDrafter(s.bedrock_model_id)
    if kind == "fake":
        from lfw.agent.fake import FakeDrafter

        return FakeDrafter(scenario or s.fake_scenario)
    raise ValueError(f"unknown draft model {kind!r}")


def run_draft(ctx: DraftContext, drafter: Drafter) -> dict:
    """Two model attempts at most, then the fixed template. Every validator result is logged."""
    attempts = []
    draft: DraftBundle | None = None
    report: ValidationReport | None = None
    errors: list[str] = []
    for n in (1, 2):
        try:
            raw = drafter.first(ctx) if n == 1 else drafter.retry(ctx, errors)
        except Exception as exc:  # model or network failure counts as a failed attempt
            raw = json.dumps({"_error": f"{type(exc).__name__}: {exc}"[:500]})
        draft, report = validate(raw, ctx)
        errors = report.errors()
        attempts.append({"attempt": n, "source": drafter.name, "passed": report.passed, "errors": errors})
        log_json("validator_result", incident_id=ctx.incident_id, attempt=n, source=drafter.name,
                 passed=report.passed, errors=errors)
        if report.passed:
            break
    template_used = not (report and report.passed)
    if template_used:
        draft, report = validate(fallback.build(ctx).model_dump(), ctx)
        attempts.append({"attempt": len(attempts) + 1, "source": "template", "passed": report.passed,
                         "errors": report.errors()})
        log_json("validator_result", incident_id=ctx.incident_id, attempt="template", source="template",
                 passed=report.passed, errors=report.errors())
    return {
        "incident_id": ctx.incident_id,
        "created_utc": utc_iso(),
        "model": drafter.name,
        "template_used": template_used,
        "validated": bool(report and report.passed),
        "attempts": attempts,
        "draft": draft.model_dump() if draft else None,
        "report": report.model_dump() if report else None,
        "hindi_enabled": ctx.hindi_enabled,
        "mode": ctx.mode,
    }


def draft_incident(incident_id: str, store: Store | None = None, kind: str | None = None,
                   scenario: str | None = None, save: bool = True, now: datetime | None = None) -> dict:
    store = store or get_store()
    ctx = build_context(store, incident_id, now or datetime.now(UTC), hindi_enabled=get_settings().hindi_enabled)
    rec = run_draft(ctx, make_drafter(kind, scenario))
    if save:
        store.put_draft(incident_id, rec["created_utc"], rec)
    return rec


def _print(rec: dict) -> None:
    d = rec["draft"]
    print(f"\n=== Draft for {rec['incident_id']} | model: {rec['model']} | "
          f"{'TEMPLATE USED' if rec['template_used'] else 'model draft'} | validated: {rec['validated']}")
    for a in rec["attempts"]:
        print(f"  attempt {a['attempt']} ({a['source']}): {'PASS' if a['passed'] else 'FAIL'}")
        for e in a["errors"]:
            print(f"      - {e}")
    if d:
        print("\n--- Resident advisory (EN)\n" + d["resident_advisory_en"])
        print("\n--- Resident advisory (HI)\n" + (d["resident_advisory_hi"] or "(Hindi disabled: not reviewed, MVP A4)"))
        print("\n--- Official alert (EN)\n" + d["official_alert_en"])
        print(f"\nreceptor_ids: {d['receptor_ids']}\nrule_keys: {d['rule_keys']}\nfacts_used: {d['facts_used']}")
    print("\n--- Validator report (final draft)")
    for c in rec["report"]["checks"]:
        mark = "PASS" if c["passed"] else ("SKIP" if c["passed"] is None else "FAIL")
        print(f"  [{mark}] {c['check']:>2}. {c['name']}" + (f" — {c['detail']}" if c["detail"] else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id")
    ap.add_argument("--model", choices=["fake", "bedrock"], default=None)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--no-store", action="store_true")
    args = ap.parse_args(argv)
    rec = draft_incident(args.incident_id, kind=args.model, scenario=args.scenario, save=not args.no_store)
    _print(rec)
    return 0 if rec["validated"] else 1


if __name__ == "__main__":
    sys.exit(main())

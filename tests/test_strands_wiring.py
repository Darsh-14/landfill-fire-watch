"""The Bedrock drafting path, exercised offline: the real Strands Agent with a scripted model.

The scripted model speaks the Strands stream-event protocol (same shapes as BedrockModel produces):
turn 1 calls the four read-only tools, turn 2 calls the structured-output tool with a draft. This
checks the wiring that only runs in AWS: tools, the tool-call log hook, structured output, the
turn limit and the time budget.
"""

import json

import pytest

pytest.importorskip("strands")

from strands.models.model import Model

from lfw.agent import fallback
from lfw.agent.fake import INVENTED_SCHOOL
from lfw.agent.run import StrandsBedrockDrafter, run_draft
from test_contract import make_ctx

OUR_TOOLS = ["get_incident", "get_smoke_zone", "list_receptors", "get_limits"]


class ScriptedModel(Model):
    def __init__(self, drafts: list[dict]):
        self.drafts = drafts  # one structured-output payload per agent invocation
        self.invocation = 0
        self.tool_spec_names: list[str] = []

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield {}  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.tool_spec_names = [t["name"] for t in tool_specs or []]
        last = messages[-1]
        answered = any("toolResult" in c for c in last.get("content", [])) if last["role"] == "user" else False
        yield {"messageStart": {"role": "assistant"}}
        if not answered:  # turn 1 of an invocation: read the facts
            calls = [(f"t{self.invocation}-{i}", n, {"incident_id": "brahmapuram-kochi-20230302T1635"} if n != "get_limits" else {})
                     for i, n in enumerate(OUR_TOOLS)]
        else:  # turn 2: return the draft through the structured-output tool
            so_tool = next(n for n in self.tool_spec_names if n not in OUR_TOOLS + ["get_rule"])
            calls = [(f"so{self.invocation}", so_tool, self.drafts[min(self.invocation, len(self.drafts) - 1)])]
            self.invocation += 1
        for tid, name, tool_input in calls:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tid, "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                            "metrics": {"latencyMs": 1}}}


def good_draft(ctx) -> dict:
    return fallback.build(ctx).model_dump()


def test_strands_agent_calls_tools_logs_them_and_returns_a_valid_draft(capsys):
    ctx = make_ctx()
    model = ScriptedModel([good_draft(ctx)])
    rec = run_draft(ctx, StrandsBedrockDrafter(model_id="test-model", model=model))
    assert rec["validated"] and not rec["template_used"], rec["attempts"]
    assert rec["model"] == "bedrock:test-model"
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    tools = [r["tool"] for r in logged if r["event"] == "agent_tool_call"]
    assert set(OUR_TOOLS) <= set(tools)  # the Strands evidence lines for CloudWatch
    assert any(r["event"] == "validator_result" and r["passed"] for r in logged)
    assert {"get_incident", "get_smoke_zone", "list_receptors", "get_rule", "get_limits"} <= set(model.tool_spec_names)


def test_invalid_model_drafts_are_rejected_and_fall_back_to_the_template():
    ctx = make_ctx()
    bad = good_draft(ctx)
    bad["official_alert_en"] = bad["official_alert_en"].replace(
        "Places in the sector, nearest first:", f"Places in the sector, nearest first: {INVENTED_SCHOOL} (school, 0.8 km);")
    rec = run_draft(ctx, StrandsBedrockDrafter(model_id="test-model", model=ScriptedModel([bad, bad])))
    assert [a["passed"] for a in rec["attempts"]] == [False, False, True]
    assert rec["template_used"] and rec["validated"]
    assert any(INVENTED_SCHOOL in e for e in rec["attempts"][0]["errors"])


def test_time_budget_stops_the_model_and_still_returns_a_validated_template():
    ctx = make_ctx()
    rec = run_draft(ctx, StrandsBedrockDrafter(model_id="test-model", model=ScriptedModel([good_draft(ctx)])),
                    time_budget_s=1e-6)
    assert rec["template_used"] and rec["validated"]
    assert "retry skipped" in rec["attempts"][1]["errors"][0]

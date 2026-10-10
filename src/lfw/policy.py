"""Cedar policy check for approvals (src/lfw/policies/approve.cedar).

Defence in depth: the approve route already enforces these rules in code (notify.topic_for, the
validated-draft check). The policy states them once, declaratively, and the route refuses to send
unless Cedar also allows it. If cedarpy is missing the check fails closed (no send).
"""

from __future__ import annotations

from pathlib import Path

POLICY = (Path(__file__).resolve().parent / "policies" / "approve.cedar").read_text(encoding="utf-8")
DUTY_OFFICER = "duty_officer"


def authorize_approve(principal_id: str, roles: list[str], incident_id: str, mode: str,
                      draft_validated: bool, topic: str) -> tuple[bool, str]:
    """(allowed, explanation). `roles` come from authentication (admin token -> duty_officer)."""
    try:
        from cedarpy import Decision, is_authorized
    except ImportError:
        return False, "policy engine unavailable (cedarpy not installed): refusing to send"
    entities = [
        {"uid": {"__entity": {"type": "User", "id": principal_id}}, "attrs": {},
         "parents": [{"__entity": {"type": "Role", "id": r}} for r in roles]},
        *({"uid": {"__entity": {"type": "Role", "id": r}}, "attrs": {}, "parents": []} for r in roles),
        {"uid": {"__entity": {"type": "Incident", "id": incident_id}},
         "attrs": {"mode": mode, "draft_validated": bool(draft_validated)}, "parents": []},
    ]
    request = {"principal": {"type": "User", "id": principal_id}, "action": {"type": "Action", "id": "approve"},
               "resource": {"type": "Incident", "id": incident_id}, "context": {"topic": topic}}
    result = is_authorized(request, POLICY, entities)
    allowed = result.decision == Decision.Allow
    reasons = getattr(result.diagnostics, "reasons", None)
    return allowed, f"cedar: {result.decision.value}" + (f" ({', '.join(reasons)})" if reasons else "")

"""DraftFunction: Strands agent on Amazon Bedrock for one incident (MVP §7, §12).

Invoked asynchronously by ApiFunction with {"incident_id": "..."}. Tool calls and validator results
are logged as JSON lines (CloudWatch Logs = the Strands evidence for the video).
"""

from __future__ import annotations

from lfw.agent.run import draft_incident
from lfw.logjson import log_json


def handler(event, context=None) -> dict:
    incident_id = event["incident_id"]
    log_json("draft_start", incident_id=incident_id)
    rec = draft_incident(incident_id)
    log_json("draft_done", incident_id=incident_id, model=rec["model"], validated=rec["validated"],
             template_used=rec["template_used"], attempts=[(a["source"], a["passed"]) for a in rec["attempts"]])
    return {"incident_id": incident_id, "validated": rec["validated"], "template_used": rec["template_used"]}

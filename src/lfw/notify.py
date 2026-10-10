"""SNS publishing for APPROVED drafts only (CLAUDE.md rules 4 and 5).

`publish_approved` is called only from the approve API route, which a person triggers with the admin
token. Replay incidents can only ever go to the demo topic.
"""

from __future__ import annotations

from lfw.models import Incident


class TopicError(ValueError):
    pass


def topic_for(mode: str, live_topic_arn: str, demo_topic_arn: str) -> tuple[str, str]:
    """(topic_kind, arn). A replay alert never goes to the live topic."""
    if mode == "replay":
        if not demo_topic_arn:
            raise TopicError("demo topic is not configured; a replay alert cannot be sent")
        return "demo", demo_topic_arn
    if mode == "live":
        if not live_topic_arn:
            raise TopicError("live topic is not configured")
        return "live", live_topic_arn
    raise TopicError(f"unknown mode {mode!r}")


def subject_for(inc: Incident, site_name: str) -> str:
    prefix = "[REPLAY] " if inc.mode == "replay" else ""
    return f"{prefix}Possible fire at {site_name} landfill — approved alert"[:100]  # SNS subject limit


def message_for(draft: dict, inc: Incident) -> str:
    d = draft["draft"]
    parts = [
        d["official_alert_en"],
        "",
        "--- Resident advisory (English) ---",
        d["resident_advisory_en"],
    ]
    if d.get("resident_advisory_hi"):
        parts += ["", "--- Resident advisory (Hindi) ---", d["resident_advisory_hi"]]
    parts += ["", f"Incident: {inc.incident_id} · mode: {inc.mode} · code status: {inc.status}",
              "Drafted by " + ("a fixed template" if draft.get("template_used") else draft.get("model", "the agent"))
              + "; checked by the validator; approved by the duty officer.",
              "Landfill Fire Watch — satellite screening, not a confirmation."]
    return "\n".join(parts)


def publish(sns_client, topic_arn: str, subject: str, message: str) -> str:
    resp = sns_client.publish(TopicArn=topic_arn, Subject=subject, Message=message)
    return resp["MessageId"]

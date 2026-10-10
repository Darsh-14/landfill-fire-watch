// Approval policy for POST /incidents/{id}/approve (prompt §9.8). Evaluated by lfw/policy.py with cedarpy.
// Deny by default: a send is allowed only if a permit matches and no forbid matches.

// Only the duty officer may approve and send an alert, and only a validated draft.
permit (
  principal in Role::"duty_officer",
  action == Action::"approve",
  resource
)
when { resource.draft_validated };

// A replay alert never goes to the live topic: replays may only be sent to the demo topic.
forbid (
  principal,
  action == Action::"approve",
  resource
)
when { resource.mode == "replay" && context.topic != "demo" };

// No send if the validator failed (or there is no draft).
forbid (
  principal,
  action == Action::"approve",
  resource
)
unless { resource.draft_validated };

"""The dashboard always shows the fixed limits text, the AWS footer and the data credits (CLAUDE.md rule 6)."""

from pathlib import Path

from lfw.agent.tools import LIMITS

WEB = Path(__file__).resolve().parents[1] / "web"


def page() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


def test_readme_lists_the_fixed_limits():
    # The dashboard no longer shows a limits panel (team decision 2026-10-11); the README keeps the full list.
    readme = (WEB.parent / "README.md").read_text(encoding="utf-8")
    for item in LIMITS:
        assert item in readme, item


def test_footer_names_aws_services_and_credits():
    p = page()
    assert "Running on AWS: EventBridge · Lambda · DynamoDB · S3 · SNS (ap-south-1) · Bedrock via Strands (us-east-1)" in p
    js = (WEB / "app.js").read_text(encoding="utf-8")  # credits live in the map attribution, shown on every screen
    assert "OpenStreetMap contributors" in js and "NASA FIRMS" in js and "Open-Meteo.com" in js and "CC BY 4.0" in js


def test_leaflet_is_loaded_from_cdnjs_with_integrity():
    p = page()
    assert 'src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"' in p and 'integrity="sha512-' in p


def test_replay_badge_and_screening_wording_in_app():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "<b>Replay</b> · historical data" in js and "Not a pollution forecast" in js and "Template used" in js


def test_flexible_controls_exist():
    p = page()
    for needle in ('id="search"', 'data-layer="hotspots"', 'data-layer="smoke"', 'data-layer="schools"',
                   'data-layer="hospitals"', 'id="btn-theme"', 'id="btn-home"', 'id="btn-panel"'):
        assert needle in p, needle
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "panel-off" in js and "localStorage" in js

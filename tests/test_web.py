"""The dashboard always shows the fixed limits text, the AWS footer and the data credits (CLAUDE.md rule 6)."""

import html
import re
from pathlib import Path

from lfw.agent.tools import LIMITS

WEB = Path(__file__).resolve().parents[1] / "web"


def page() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


def test_limits_panel_matches_the_fixed_text():
    items = [html.unescape(x.strip()) for x in re.findall(r"<li>(.*?)</li>", page().split('id="limits"')[1].split("</aside>")[0], re.S)]
    assert items == LIMITS


def test_footer_names_aws_services_and_credits():
    p = page()
    assert "Running on AWS (ap-south-1): EventBridge · Lambda · DynamoDB · S3 · Bedrock (Strands) · SNS" in p
    assert "Fire Information for Resource Management" in p and "OpenStreetMap contributors" in p and "CC BY 4.0" in p


def test_leaflet_is_loaded_from_cdnjs_with_integrity():
    p = page()
    assert 'src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"' in p and 'integrity="sha512-' in p


def test_replay_badge_and_screening_wording_in_app():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "REPLAY — historical data" in js and "Not a pollution forecast" in js and "Template used" in js

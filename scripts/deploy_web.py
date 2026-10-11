"""Deploy web/ to AWS Amplify Hosting (manual deploy, no Git connection).

1. Reads the stack output ApiUrl and writes web/config.js.
2. Creates the Amplify app + branch on first run (reuses them later).
3. Zips web/, creates a deployment, uploads the zip, starts the deployment, waits for it.
Prints the dashboard URL. Then restrict CORS: make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=... ALLOWED_ORIGIN=<url>.

Usage: python scripts/deploy_web.py [--app-name landfill-fire-watch] [--branch main] [--amplify-region us-east-1]
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aws_common import session, stack_outputs  # noqa: E402

WEB = HERE.parent / "web"


def zip_web() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(WEB.iterdir()):
            if p.is_file():
                z.write(p, p.name)  # files at the zip root
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-name", default="landfill-fire-watch")
    ap.add_argument("--branch", default="main")
    # Amplify limits apps per region per account; the static site can live in another region.
    ap.add_argument("--amplify-region", default=None, help="default: the stack region")
    args = ap.parse_args()
    api_url = stack_outputs()["ApiUrl"]
    (WEB / "config.js").write_text(
        "// Written by scripts/deploy_web.py from the stack output ApiUrl.\n"
        f'window.LFW_CONFIG = {{ apiBase: "{api_url}" }};\n', encoding="utf-8", newline="\n")
    print(f"web/config.js -> {api_url}")

    amp = session().client("amplify", region_name=args.amplify_region)
    app = next((a for a in amp.list_apps()["apps"] if a["name"] == args.app_name), None)
    if app is None:
        app = amp.create_app(name=args.app_name, platform="WEB")["app"]
        print(f"created Amplify app {app['appId']}")
    app_id = app["appId"]
    branches = [b["branchName"] for b in amp.list_branches(appId=app_id)["branches"]]
    if args.branch not in branches:
        amp.create_branch(appId=app_id, branchName=args.branch)
    dep = amp.create_deployment(appId=app_id, branchName=args.branch)
    httpx.put(dep["zipUploadUrl"], content=zip_web(), headers={"Content-Type": "application/zip"},
              timeout=120).raise_for_status()
    job = amp.start_deployment(appId=app_id, branchName=args.branch, jobId=dep["jobId"])["jobSummary"]
    for _ in range(60):
        status = amp.get_job(appId=app_id, branchName=args.branch, jobId=job["jobId"])["job"]["summary"]["status"]
        if status in ("SUCCEED", "FAILED", "CANCELLED"):
            break
        time.sleep(5)
    url = f"https://{args.branch}.{app['defaultDomain']}"
    print(f"Amplify deployment {status}: {url}")
    print(f"Next, lock CORS to this origin: make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=... ALLOWED_ORIGIN={url}")
    return 0 if status == "SUCCEED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

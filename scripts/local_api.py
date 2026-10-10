"""Serve the API locally on port 8001 (STORE=local) so `make web` works without AWS.

Same route() code as the Lambda. Differences, by design:
  * approve writes the message to out/outbox/ instead of SNS (printed to the console),
  * drafting runs synchronously with the fake model (no Bedrock locally).
Admin token: ADMIN_TOKEN from .env; if empty, a random token is printed at start.

Usage: python scripts/local_api.py [--port 8001]
"""

from __future__ import annotations

import argparse
import json
import secrets as pysecrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handlers import api  # noqa: E402
from lfw import secrets  # noqa: E402
from lfw.agent.run import draft_incident  # noqa: E402
from lfw.store import LocalStore  # noqa: E402
from lfw.timeutil import utc_iso  # noqa: E402

OUTBOX = ROOT / "out" / "outbox"


def make_deps(token: str) -> api.Deps:
    store = LocalStore()

    def publish(arn: str, subject: str, message: str) -> str:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        mid = f"local-{utc_iso().replace(':', '')}"
        (OUTBOX / f"{mid}.txt").write_text(f"To topic: {arn}\nSubject: {subject}\n\n{message}\n", encoding="utf-8")
        print(f"\n[outbox] {arn}\nSubject: {subject}\n{message}\n", flush=True)
        return mid

    def start_draft(incident_id: str) -> dict:
        rec = draft_incident(incident_id, store=store)
        return {"status": "done", "incident_id": incident_id, "validated": rec["validated"]}

    def backtest() -> dict | None:
        p = ROOT / "out" / "backtest.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    return api.Deps(store=store, admin_token=lambda: token, publish=publish, start_draft=start_draft,
                    live_topic_arn="local:LiveTopic", demo_topic_arn="local:DemoTopic", backtest=backtest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    token = secrets.admin_token() or pysecrets.token_urlsafe(16)
    if not secrets.admin_token():
        print(f"ADMIN_TOKEN not set in .env; using this token for this session: {token}", flush=True)
    deps = make_deps(token)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, out: dict) -> None:
            body = out["body"].encode("utf-8")
            self.send_response(out["statusCode"])
            self.send_header("content-type", "application/json")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-headers", "content-type, x-admin-token")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self, method: str) -> None:
            u = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n).decode("utf-8") if n else None
            self._send(api.route(method, u.path, {}, query, dict(self.headers), body, deps))

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def do_OPTIONS(self):  # noqa: N802
            self._send({"statusCode": 204, "body": ""})

        def log_message(self, fmt, *a):
            sys.stderr.write("[api-local] " + fmt % a + "\n")

    print(f"Local API on http://localhost:{args.port} (STORE=local). Open the dashboard with `make web`.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

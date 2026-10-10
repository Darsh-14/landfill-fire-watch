"""`make verify`: re-download each source document in data/sources.yaml and compare SHA-256 (MVP §13).

Prints OK / CHANGED / UNREACHABLE / NOT RECORDED per source. HTML pages often change (ads, scripts),
so CHANGED on a web page means "re-read the quote", not "the claim is wrong". PDFs should stay OK.
News sites are not downloaded by code (CLAUDE.md §9); they are listed in data/events.yaml with the
quote a person read.

Usage:
  python scripts/verify_sources.py            # verify
  python scripts/verify_sources.py --record   # fill sha256 / retrieved for entries that have none
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, FetchError, request, utc_now_iso  # noqa: E402

SOURCES = ROOT / "data" / "sources.yaml"
HEADER = ("# Source documents (MVP §13): URL, title, retrieved date, SHA-256, S3 key.\n"
          "# `make verify` re-downloads each one and compares the SHA-256. News sites are not downloaded by\n"
          "# code (CLAUDE.md §9); see data/events.yaml for the quotes a person read on those pages.\n")


def fetch(url: str) -> bytes:
    return request("GET", url, timeout=60, follow_redirects=True,
                   headers={"Accept": "*/*", "User-Agent": "Mozilla/5.0 (LandfillFireWatch verify)"}).content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args()
    entries = yaml.safe_load(SOURCES.read_text(encoding="utf-8")) or []
    worst = 0
    for e in entries:
        if not e.get("url"):
            print(f"MISSING      {e['id']}: no URL ({e.get('note', '')})")
            continue
        try:
            body = fetch(e["url"])
        except FetchError as exc:
            print(f"UNREACHABLE  {e['id']}: {str(exc)[:120]}")
            worst = max(worst, 1)
            continue
        if e.get("kind") == "pdf" and not body.lstrip().startswith(b"%PDF"):
            print(f"NOT A PDF    {e['id']}: the URL returned {body[:15]!r}… (document moved?)")
            worst = max(worst, 2)
            continue
        digest = hashlib.sha256(body).hexdigest()
        if args.record and not e.get("sha256"):
            e.update(sha256=digest, retrieved_utc=utc_now_iso(), bytes=len(body))
            print(f"RECORDED     {e['id']}: {digest[:16]}… ({len(body)} bytes)")
        elif not e.get("sha256"):
            print(f"NOT RECORDED {e['id']}: run with --record")
        elif digest == e["sha256"]:
            print(f"OK           {e['id']}")
        else:
            print(f"CHANGED      {e['id']}: was {e['sha256'][:12]}…, now {digest[:12]}… ({e.get('kind', '')})")
            worst = max(worst, 1 if e.get("kind") == "html" else 2)
    if args.record:
        SOURCES.write_text(HEADER + yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=200),
                           encoding="utf-8", newline="\n")
    return 0 if worst < 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())

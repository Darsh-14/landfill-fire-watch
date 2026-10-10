"""JSON-lines logging (CLAUDE.md §8). In Lambda, stdout goes to CloudWatch Logs."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime


def log_json(event: str, **fields) -> None:
    rec = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "event": event, **fields}
    print(json.dumps(rec, ensure_ascii=False, default=str), file=sys.stdout, flush=True)

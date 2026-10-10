"""Shared helpers for scripts/. HTTP goes through lfw.http (timeouts, retries, key redaction)."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from lfw.http import FetchError
from lfw.http import request as _request

ROOT = Path(__file__).resolve().parent.parent

__all__ = ["ROOT", "FetchError", "log", "request", "sha256_bytes", "utc_now_iso"]


def request(method: str, url: str, *, redact: tuple[str, ...] = (), **kwargs) -> httpx.Response:
    return _request(method, url, redact_values=redact, **kwargs)


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

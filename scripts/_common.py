"""Shared helpers for scripts/: HTTP with timeout, 2 retries and backoff (CLAUDE.md §8)."""

from __future__ import annotations

import hashlib
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from lfw.config import HTTP_BACKOFF_S, HTTP_RETRIES, HTTP_TIMEOUT_S, USER_AGENT

ROOT = Path(__file__).resolve().parent.parent


class FetchError(RuntimeError):
    """Final HTTP failure. The message is redacted (no secrets, e.g. the FIRMS key in the URL)."""


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def request(
    method: str,
    url: str,
    *,
    timeout: float = HTTP_TIMEOUT_S,
    redact: tuple[str, ...] = (),
    **kwargs,
) -> httpx.Response:
    """Send a request; retry on network errors, 429 and 5xx. Raise FetchError on final failure."""
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    last_msg = ""
    for attempt in range(HTTP_RETRIES + 1):
        retryable = True
        try:
            resp = httpx.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if resp.status_code < 400:
                return resp
            retryable = resp.status_code == 429 or resp.status_code >= 500
            last_msg = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except httpx.TransportError as exc:
            last_msg = f"{type(exc).__name__}: {exc}"
        if attempt == HTTP_RETRIES or not retryable:
            break
        time.sleep(HTTP_BACKOFF_S * (2**attempt))
    raise FetchError(_redact(f"{method} {url} failed: {last_msg}", redact)) from None


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

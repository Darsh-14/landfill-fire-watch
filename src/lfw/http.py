"""HTTP with timeout, 2 retries and backoff (CLAUDE.md §8). Used only by firms.py, wind.py and scripts/.

Error messages are redacted: the FIRMS MAP_KEY is part of the URL path and must never be printed.
"""

from __future__ import annotations

import time

import httpx

from lfw.config import HTTP_BACKOFF_S, HTTP_RETRIES, HTTP_TIMEOUT_S, USER_AGENT


class FetchError(RuntimeError):
    """Final HTTP failure. The message never contains a secret."""


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def request(
    method: str,
    url: str,
    *,
    timeout: float = HTTP_TIMEOUT_S,
    redact_values: tuple[str, ...] = (),
    retries: int = HTTP_RETRIES,
    **kwargs,
) -> httpx.Response:
    """Send a request; retry on network errors, 429 and 5xx. Raise FetchError on final failure."""
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    last_msg = ""
    for attempt in range(retries + 1):
        retryable = True
        try:
            resp = httpx.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if resp.status_code < 400:
                return resp
            retryable = resp.status_code == 429 or resp.status_code >= 500
            last_msg = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except httpx.TransportError as exc:
            last_msg = f"{type(exc).__name__}: {exc}"
        if attempt == retries or not retryable:
            break
        time.sleep(HTTP_BACKOFF_S * (2**attempt))
    raise FetchError(redact(f"{method} {url} failed: {last_msg}", redact_values)) from None

"""Time formatting. Store UTC; show IST (CLAUDE.md §6)."""

from __future__ import annotations

from datetime import UTC, datetime

from lfw.config import IST


def ist_str(dt: datetime | None) -> str | None:
    """'2023-03-02 22:05 IST' — the one format used in drafts, facts_used and the UI."""
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST") if dt else None


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

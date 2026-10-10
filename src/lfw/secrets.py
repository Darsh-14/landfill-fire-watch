"""Secrets at runtime: SSM Parameter Store in AWS, `.env` locally (CLAUDE.md rule 8). Never logged."""

from __future__ import annotations

import os

from lfw.config import get_settings

_cache: dict[str, str] = {}


def _ssm_get(name: str) -> str:
    if name not in _cache:
        import boto3

        resp = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
        _cache[name] = resp["Parameter"]["Value"]
    return _cache[name]


def firms_key() -> str:
    """FIRMS MAP_KEY from SSM (env FIRMS_KEY_PARAM) or from .env (FIRMS_MAP_KEY)."""
    if os.environ.get("FIRMS_KEY_PARAM"):
        return _ssm_get(os.environ["FIRMS_KEY_PARAM"])
    s = get_settings().firms_map_key
    return s.get_secret_value() if s else ""


def admin_token() -> str:
    """Admin token from SSM (env ADMIN_TOKEN_PARAM) or from .env (ADMIN_TOKEN)."""
    if os.environ.get("ADMIN_TOKEN_PARAM"):
        return _ssm_get(os.environ["ADMIN_TOKEN_PARAM"])
    s = get_settings().admin_token
    return s.get_secret_value() if s else ""

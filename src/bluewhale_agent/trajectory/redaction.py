"""Recursive credential redaction applied before trajectory persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(?:^|_)(?:API_KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION)$",
    flags=re.IGNORECASE,
)
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_BEARER_HEADER = re.compile(
    r"(Authorization\s*:\s*Bearer\s+)[^\s,;]+",
    flags=re.IGNORECASE,
)
_ENV_SECRET = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))=([^\s]+)",
    flags=re.IGNORECASE,
)


def redact(value: object) -> object:
    """Return a recursively redacted copy of a JSON-compatible value."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_secret_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _is_secret_key(key: str) -> bool:
    return _SECRET_KEY.search(key) is not None


def _redact_text(text: str) -> str:
    text = _BEARER_HEADER.sub(r"\1[REDACTED]", text)
    text = _ENV_SECRET.sub(r"\1=[REDACTED]", text)
    return _SK_TOKEN.sub(REDACTED, text)


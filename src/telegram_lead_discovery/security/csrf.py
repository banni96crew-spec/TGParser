from __future__ import annotations

import secrets


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf_token(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)

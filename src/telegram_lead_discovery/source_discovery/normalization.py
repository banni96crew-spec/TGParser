"""Pure username normalization for source discovery."""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")


class InvalidUsernameError(ValueError):
    pass


def normalize_username(value: str) -> str:
    text = value.strip()
    lower = text.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            lower = text.lower()
            break
    text = text.lstrip("@")
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    text = text.lower()
    if not USERNAME_RE.fullmatch(text):
        raise InvalidUsernameError(f"invalid_username:{value!r}")
    return text


__all__ = ["InvalidUsernameError", "USERNAME_RE", "normalize_username"]

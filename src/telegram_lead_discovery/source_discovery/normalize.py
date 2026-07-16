from __future__ import annotations

import re
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")


def normalize_source_ref(raw: str) -> str:
    value = raw.strip()
    lowered = value.lower()
    for prefix in ("https://", "http://"):
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            lowered = value.lower()
            break
    if lowered.startswith("t.me/"):
        value = value[5:]
        lowered = value.lower()
    if value.startswith("@"):
        value = value[1:]
    if "?" in value:
        value = value.split("?", 1)[0]
    if "#" in value:
        value = value.split("#", 1)[0]
    value = value.strip("/")
    # If still a URL path like t.me/xxx after parse
    if "/" in value and not value.startswith("@"):
        parsed = urlparse("https://" + value if "://" not in value else value)
        path = parsed.path.strip("/")
        value = path.split("/")[0] if path else value
    value = value.lower()
    if not USERNAME_RE.match(value):
        raise ValueError("invalid_source_ref")
    return value

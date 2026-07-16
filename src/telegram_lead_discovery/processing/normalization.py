"""Text normalization and content fingerprints (PROC-003 / PROC-004)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = (
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\ufeff",  # BOM / ZERO WIDTH NO-BREAK SPACE
)

_MULTI_LF = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s+", re.UNICODE)

ANALYSIS_MAX_CODEPOINTS = 4096


@dataclass(frozen=True, slots=True)
class NormalizedTexts:
    display_text: str
    dedup_text: str
    analysis_text: str
    analysis_truncated: bool
    dedup_hash: str
    content_fingerprint: str


def build_display_text(raw: str | None) -> str:
    text = "" if raw is None else str(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")
    text = _MULTI_LF.sub("\n\n", text)
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return text.strip()


def build_dedup_text(display_text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", display_text).strip()
    return collapsed.casefold()


def build_analysis_text(dedup_text: str) -> tuple[str, bool]:
    if len(dedup_text) <= ANALYSIS_MAX_CODEPOINTS:
        return dedup_text, False
    return dedup_text[:ANALYSIS_MAX_CODEPOINTS], True


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_fingerprint(
    display_text: str,
    *,
    author_peer_id: str | int | None = None,
    edited_at: str | None = None,
) -> str:
    author = "" if author_peer_id is None else str(author_peer_id)
    edited = "" if edited_at is None else edited_at
    payload = f"{display_text}\n{author}\n{edited}"
    return sha256_hex(payload)


def normalize_message_text(
    raw: str | None,
    *,
    author_peer_id: str | int | None = None,
    edited_at: str | None = None,
) -> NormalizedTexts:
    display = build_display_text(raw)
    dedup = build_dedup_text(display)
    analysis, truncated = build_analysis_text(dedup)
    return NormalizedTexts(
        display_text=display,
        dedup_text=dedup,
        analysis_text=analysis,
        analysis_truncated=truncated,
        dedup_hash=sha256_hex(dedup),
        content_fingerprint=content_fingerprint(
            display, author_peer_id=author_peer_id, edited_at=edited_at
        ),
    )


# Alias for tests / callers expecting normalize_message
normalize_message = normalize_message_text

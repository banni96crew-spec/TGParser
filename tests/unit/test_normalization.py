"""Unit tests — PROC-003 / PROC-004 normalization."""

from __future__ import annotations

from telegram_lead_discovery.processing.normalization import (
    normalize_message_text,
    sha256_hex,
)


def test_proc_003_crlf_nfkc_zwsp_whitespace() -> None:
    raw = "A\r\nB\u200b  C\n\n\n\nD  "
    result = normalize_message_text(raw)
    assert "\r" not in result.display_text
    assert "\u200b" not in result.display_text
    assert "\n\n\n" not in result.display_text
    assert result.display_text == "A\nB  C\n\nD"
    assert result.dedup_text == "a b c d"
    assert result.analysis_text == result.dedup_text
    assert result.analysis_truncated is False


def test_proc_004_fingerprints_stable() -> None:
    edited = "2026-01-01T00:00:00+00:00"
    a = normalize_message_text("Hello\r\nWorld", author_peer_id=42, edited_at=edited)
    b = normalize_message_text("Hello\r\nWorld", author_peer_id=42, edited_at=edited)
    assert a.dedup_hash == b.dedup_hash == sha256_hex(a.dedup_text)
    assert a.content_fingerprint == b.content_fingerprint
    assert len(a.dedup_hash) == 64
    assert a.dedup_hash == a.dedup_hash.lower()


def test_analysis_text_cap_4096() -> None:
    raw = "x" * 5000
    result = normalize_message_text(raw)
    assert len(result.analysis_text) == 4096
    assert result.analysis_truncated is True

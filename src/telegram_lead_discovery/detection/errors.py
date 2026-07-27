"""Detection / rule-set load errors (DET-016 / PROC-019)."""

from __future__ import annotations


class RuleSetInvalidError(Exception):
    """Missing rule-set version or checksum mismatch — permanent, no SEED fallback."""

    error_code = "RULE_SET_INVALID"

    def __init__(self, message: str = "rule_set_invalid") -> None:
        super().__init__(message)
        self.message = message

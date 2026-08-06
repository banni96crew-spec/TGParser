"""Immutable DET-A seed rule catalogs."""

from __future__ import annotations

from dataclasses import dataclass

RULE_FLAGS = "IGNORECASE|FULLCASE|VERSION1"


@dataclass(frozen=True, slots=True)
class SeedRule:
    stable_rule_id: str
    priority: int
    target: str
    dimension: str
    weight: int
    pattern: str
    explanation_code: str
    kind: str


def _kind_for(dimension: str) -> str:
    if dimension == "hard_exclusion":
        return "hard_exclusion"
    if dimension == "service_fit":
        return "service"
    if dimension == "intent":
        return "positive_intent"
    return "signal"


def _r(
    rule_id: str,
    priority: int,
    target: str,
    dimension: str,
    weight: int,
    pattern: str,
    explanation_code: str,
) -> SeedRule:
    return SeedRule(
        stable_rule_id=rule_id,
        priority=priority,
        target=target,
        dimension=dimension,
        weight=weight,
        pattern=pattern,
        explanation_code=explanation_code,
        kind=_kind_for(dimension),
    )

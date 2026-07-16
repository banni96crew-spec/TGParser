"""Rule-based lead detection engine (DET-007..DET-013)."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import regex

from telegram_lead_discovery.detection.seed import SEED_RULES, SeedRule, catalog_checksum

REGEX_TIMEOUT = 0.05
MATCHED_EXCERPT_MAX = 120
REGEX_FLAGS = regex.IGNORECASE | regex.FULLCASE | regex.VERSION1

HARD_EXCLUSION_PRECEDENCE = ("spam", "advertising", "vacancy")
POSITIVE_PRECEDENCE = (
    "direct_order",
    "contractor_search",
    "recommendation_request",
    "potential_need",
)

SIGNAL_TARGETS = {
    "budget_present",
    "deadline_present",
    "urgency_present",
    "ready_to_start",
    "contact_present",
    "task_specificity",
}


@dataclass(frozen=True, slots=True)
class MatchedRule:
    stable_rule_id: str
    rule_type: str
    dimension: str
    weight: int
    matched_excerpt: str
    target: str
    explanation_code: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    category: str
    is_lead: bool
    hard_exclusion: bool
    hard_exclusion_rule_id: str | None
    matched_rules: tuple[MatchedRule, ...]
    service_profiles: tuple[str, ...]
    timed_out_rule_ids: tuple[str, ...]
    signals: dict[str, bool]
    explanation_codes: tuple[str, ...]
    duration_ms: int
    rule_set_checksum: str = field(default_factory=catalog_checksum)


def _compile(rule: SeedRule) -> regex.Pattern[str]:
    return regex.compile(rule.pattern, flags=REGEX_FLAGS)


_COMPILED: dict[str, regex.Pattern[str]] = {
    rule.stable_rule_id: _compile(rule) for rule in SEED_RULES
}


def _excerpt(match: regex.Match[str]) -> str:
    text = match.group(0)
    if len(text) <= MATCHED_EXCERPT_MAX:
        return text
    return text[:MATCHED_EXCERPT_MAX]


def _search(rule: SeedRule, text: str) -> tuple[MatchedRule | None, bool]:
    pattern = _COMPILED[rule.stable_rule_id]
    try:
        match = pattern.search(text, timeout=REGEX_TIMEOUT)
    except TimeoutError:
        return None, True
    if match is None:
        return None, False
    return (
        MatchedRule(
            stable_rule_id=rule.stable_rule_id,
            rule_type=rule.kind,
            dimension=rule.dimension,
            weight=rule.weight,
            matched_excerpt=_excerpt(match),
            target=rule.target,
            explanation_code=rule.explanation_code,
        ),
        False,
    )


def detect(analysis_text: str, *, rules: tuple[SeedRule, ...] | None = None) -> DetectionResult:
    started = perf_counter()
    catalog = rules if rules is not None else SEED_RULES
    ordered = sorted(catalog, key=lambda r: (r.priority, r.stable_rule_id))

    matched: list[MatchedRule] = []
    timed_out: list[str] = []
    hard_hits: list[MatchedRule] = []
    intent_hits: list[MatchedRule] = []
    service_hits: list[MatchedRule] = []
    signal_hits: list[MatchedRule] = []

    for rule in ordered:
        hit, timed = _search(rule, analysis_text)
        if timed:
            timed_out.append(rule.stable_rule_id)
            continue
        if hit is None:
            continue
        matched.append(hit)
        if rule.kind == "hard_exclusion":
            hard_hits.append(hit)
        elif rule.kind == "positive_intent":
            intent_hits.append(hit)
        elif rule.kind == "service":
            service_hits.append(hit)
        else:
            signal_hits.append(hit)

    hard_exclusion_rule_id: str | None = None
    category = "irrelevant"
    is_lead = False
    hard_exclusion = False

    if hard_hits:
        hard_exclusion = True
        by_target = {h.target: h for h in hard_hits}
        for target in HARD_EXCLUSION_PRECEDENCE:
            if target in by_target:
                category = target
                hard_exclusion_rule_id = by_target[target].stable_rule_id
                break
        is_lead = False
    elif intent_hits and service_hits:
        by_target = {h.target: h for h in intent_hits}
        for target in POSITIVE_PRECEDENCE:
            if target in by_target:
                category = target
                break
        is_lead = True
    else:
        category = "irrelevant"
        is_lead = False

    service_profiles = tuple(sorted({h.target for h in service_hits}))
    signals = {name: False for name in SIGNAL_TARGETS}
    for hit in signal_hits:
        if hit.target in signals:
            signals[hit.target] = True

    duration_ms = int((perf_counter() - started) * 1000)
    return DetectionResult(
        category=category,
        is_lead=is_lead,
        hard_exclusion=hard_exclusion,
        hard_exclusion_rule_id=hard_exclusion_rule_id,
        matched_rules=tuple(matched),
        service_profiles=service_profiles,
        timed_out_rule_ids=tuple(timed_out),
        signals=signals,
        explanation_codes=tuple(m.explanation_code for m in matched),
        duration_ms=duration_ms,
    )

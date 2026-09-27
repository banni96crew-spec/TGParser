"""Rule-based lead detection engine (DET-007..DET-016)."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import regex

from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES, SeedRule
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.errors import RuleSetInvalidError

REGEX_TIMEOUT = 0.05
MATCHED_EXCERPT_MAX = 120
ANALYSIS_TEXT_CAP = 4096
REGEX_FLAGS = regex.IGNORECASE | regex.FULLCASE | regex.VERSION1

HARD_EXCLUSION_PRECEDENCE = ("spam", "advertising")
POSITIVE_PRECEDENCE = (
    "direct_order",
    "contractor_search",
    "recommendation_request",
    "vacancy",
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

# Compile cache key = catalog checksum (DET-016).
_COMPILE_CACHE: dict[str, dict[str, regex.Pattern[str]]] = {}


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
    rule_set_checksum: str
    # Defaults preserve compatibility with callers that construct detection
    # results directly (for example, source-discovery tests and adapters).
    author_role: str = "neutral"
    author_role_rule_ids: tuple[str, ...] = ()


def clear_compile_cache() -> None:
    _COMPILE_CACHE.clear()


def _compile(rule: SeedRule) -> regex.Pattern[str]:
    return regex.compile(rule.pattern, flags=REGEX_FLAGS)


def _compiled_for(checksum: str, rules: tuple[SeedRule, ...]) -> dict[str, regex.Pattern[str]]:
    cached = _COMPILE_CACHE.get(checksum)
    if cached is not None:
        return cached
    compiled = {rule.stable_rule_id: _compile(rule) for rule in rules}
    _COMPILE_CACHE[checksum] = compiled
    return compiled


def _excerpt(match: regex.Match[str]) -> str:
    text = match.group(0)
    if len(text) <= MATCHED_EXCERPT_MAX:
        return text
    return text[:MATCHED_EXCERPT_MAX]


def _cap_analysis_text(analysis_text: str) -> str:
    if len(analysis_text) <= ANALYSIS_TEXT_CAP:
        return analysis_text
    return analysis_text[:ANALYSIS_TEXT_CAP]


def _role_analysis_text(analysis_text: str) -> str:
    """Ignore explicit quote lines when inferring the current author's role."""
    return "\n".join(
        "" if line.lstrip().startswith((">", "↪")) else line
        for line in analysis_text.splitlines()
    )


def _search(
    rule: SeedRule,
    text: str,
    compiled: dict[str, regex.Pattern[str]],
) -> tuple[MatchedRule | None, bool]:
    pattern = compiled[rule.stable_rule_id]
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


def detect(
    analysis_text: str,
    *,
    rules: tuple[SeedRule, ...],
    rule_set_checksum: str,
) -> DetectionResult:
    """Evaluate analysis text against an explicitly pinned rule catalog.

    Runtime MUST pass rules loaded by version+checksum. Missing/mismatched
    catalogs are rejected by the loader before this call — never silently
    substitute SEED_RULES (DET-016 / D-065).
    """
    if not rule_set_checksum:
        raise RuleSetInvalidError("missing_checksum")
    if not rules:
        raise RuleSetInvalidError("empty_rule_catalog")

    content_checksum = catalog_checksum(rules)
    if content_checksum != rule_set_checksum:
        raise RuleSetInvalidError("checksum_mismatch")

    text = _cap_analysis_text(analysis_text)
    role_text = _role_analysis_text(text)
    started = perf_counter()
    compiled = _compiled_for(rule_set_checksum, rules)
    ordered = sorted(rules, key=lambda r: (r.priority, r.stable_rule_id))

    matched: list[MatchedRule] = []
    timed_out: list[str] = []
    hard_hits: list[MatchedRule] = []
    intent_hits: list[MatchedRule] = []
    service_hits: list[MatchedRule] = []
    signal_hits: list[MatchedRule] = []
    role_hits: list[MatchedRule] = []

    for rule in ordered:
        hit, timed = _search(rule, role_text if rule.kind == "author_role" else text, compiled)
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
        elif rule.kind == "author_role":
            role_hits.append(hit)
        else:
            signal_hits.append(hit)

    hard_exclusion_rule_id: str | None = None
    category = "irrelevant"
    is_lead = False
    hard_exclusion = False
    author_role = "neutral"
    author_role_rule_ids: tuple[str, ...] = ()

    role_by_target: dict[str, list[MatchedRule]] = {}
    for hit in role_hits:
        role_by_target.setdefault(hit.target, []).append(hit)
    if "provider_offer" in role_by_target:
        author_role = "provider_offer"
    elif "job_seeker" in role_by_target:
        author_role = "job_seeker"
    elif "vacancy" in role_by_target:
        author_role = "vacancy"
    elif "client_request" in role_by_target:
        author_role = "client_request"
    author_role_rule_ids = tuple(
        sorted(hit.stable_rule_id for hit in role_by_target.get(author_role, []))
    )

    if hard_hits:
        hard_exclusion = True
        by_target = {h.target: h for h in hard_hits}
        for target in HARD_EXCLUSION_PRECEDENCE:
            if target in by_target:
                category = target
                hard_exclusion_rule_id = by_target[target].stable_rule_id
                break
        is_lead = False
    elif author_role in {"provider_offer", "job_seeker"}:
        # A self-description of services is not a client request even if it
        # contains generic wording such as "моя задача — сделать".
        category = "advertising"
        hard_exclusion = True
        hard_exclusion_rule_id = author_role_rule_ids[0]
        is_lead = False
    elif author_role == "vacancy" and intent_hits:
        # Keep every explicit vacancy visible. Only a vacancy that also names
        # a supported service is an eligible lead (D-081); unsupported hiring
        # remains a non-lead vacancy instead of becoming irrelevant.
        category = "vacancy"
        is_lead = bool(service_hits)
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
        author_role=author_role,
        author_role_rule_ids=author_role_rule_ids,
        duration_ms=duration_ms,
        rule_set_checksum=rule_set_checksum,
    )


def stable_detection_payload(result: DetectionResult) -> dict[str, object]:
    """Byte-stable structured view (excludes wall-clock duration_ms)."""
    return {
        "category": result.category,
        "is_lead": result.is_lead,
        "hard_exclusion": result.hard_exclusion,
        "hard_exclusion_rule_id": result.hard_exclusion_rule_id,
        "matched_rules": [
            {
                "stable_rule_id": m.stable_rule_id,
                "rule_type": m.rule_type,
                "dimension": m.dimension,
                "weight": m.weight,
                "matched_excerpt": m.matched_excerpt,
                "target": m.target,
                "explanation_code": m.explanation_code,
            }
            for m in result.matched_rules
        ],
        "service_profiles": list(result.service_profiles),
        "timed_out_rule_ids": list(result.timed_out_rule_ids),
        "signals": dict(sorted(result.signals.items())),
        "explanation_codes": list(result.explanation_codes),
        "author_role": result.author_role,
        "author_role_rule_ids": list(result.author_role_rule_ids),
        "rule_set_checksum": result.rule_set_checksum,
    }


def seed_catalog_detect(analysis_text: str) -> DetectionResult:
    """Explicit SEED catalog detect for unit/scouting fixtures (not a runtime fallback)."""
    return detect(
        analysis_text,
        rules=ACTIVE_SEED_RULES,
        rule_set_checksum=catalog_checksum(ACTIVE_SEED_RULES),
    )

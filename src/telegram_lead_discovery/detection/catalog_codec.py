"""Canonical serialization and checksums for DET-A catalogs."""

from __future__ import annotations

import hashlib
import json

from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES, RULE_FLAGS, SeedRule


def catalog_canonical_json(rules: tuple[SeedRule, ...] | None = None) -> str:
    catalog = rules if rules is not None else ACTIVE_SEED_RULES
    payload = [
        {
            "stable_rule_id": r.stable_rule_id,
            "priority": r.priority,
            "target": r.target,
            "dimension": r.dimension,
            "weight": r.weight,
            "pattern": r.pattern,
            "explanation_code": r.explanation_code,
            "kind": r.kind,
            "flags": RULE_FLAGS,
            "enabled": True,
        }
        for r in catalog
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def catalog_checksum(rules: tuple[SeedRule, ...] | None = None) -> str:
    return hashlib.sha256(catalog_canonical_json(rules).encode("utf-8")).hexdigest()



__all__ = ["catalog_canonical_json", "catalog_checksum"]


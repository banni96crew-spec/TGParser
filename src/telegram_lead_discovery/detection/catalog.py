"""Immutable DET-A seed rule catalogs."""

from telegram_lead_discovery.detection.catalog_types import RULE_FLAGS, SeedRule
from telegram_lead_discovery.detection.catalog_v1 import SEED_RULES
from telegram_lead_discovery.detection.catalog_versions import (
    ACTIVE_SEED_RULES,
    SEED_RULES_RU_MVP_2,
    SEED_RULES_RU_MVP_3,
    SEED_RULES_RU_MVP_4,
)

__all__ = [
    "ACTIVE_SEED_RULES",
    "RULE_FLAGS",
    "SEED_RULES",
    "SEED_RULES_RU_MVP_2",
    "SEED_RULES_RU_MVP_3",
    "SEED_RULES_RU_MVP_4",
    "SeedRule",
]

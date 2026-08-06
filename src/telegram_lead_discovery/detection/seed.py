"""Compatibility facade for detection catalogs and their persistence."""

from telegram_lead_discovery.detection import catalog as _catalog
from telegram_lead_discovery.detection import catalog_codec as _codec
from telegram_lead_discovery.detection import catalog_persistence as _persistence

ACTIVE_SEED_RULES = _catalog.ACTIVE_SEED_RULES
RULE_FLAGS = _catalog.RULE_FLAGS
SEED_RULES = _catalog.SEED_RULES
SEED_RULES_RU_MVP_2 = _catalog.SEED_RULES_RU_MVP_2
SEED_RULES_RU_MVP_3 = _catalog.SEED_RULES_RU_MVP_3
SEED_RULES_RU_MVP_4 = _catalog.SEED_RULES_RU_MVP_4
SeedRule = _catalog.SeedRule

catalog_canonical_json = _codec.catalog_canonical_json
catalog_checksum = _codec.catalog_checksum

_insert_ruleset = _persistence._insert_ruleset
seed_ruleset_ru_mvp_1 = _persistence.seed_ruleset_ru_mvp_1
seed_ruleset_ru_mvp_2 = _persistence.seed_ruleset_ru_mvp_2
seed_ruleset_ru_mvp_3 = _persistence.seed_ruleset_ru_mvp_3
seed_ruleset_ru_mvp_4 = _persistence.seed_ruleset_ru_mvp_4
get_active_ruleset = _persistence.get_active_ruleset
seed_active_ruleset = _persistence.seed_active_ruleset

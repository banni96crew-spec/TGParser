"""Assembly of the immutable ru-mvp-1 catalog."""

from telegram_lead_discovery.detection.catalog_v1_a import RULES_V1_A
from telegram_lead_discovery.detection.catalog_v1_b import RULES_V1_B
from telegram_lead_discovery.detection.catalog_v1_c import RULES_V1_C

SEED_RULES = RULES_V1_A + RULES_V1_B + RULES_V1_C

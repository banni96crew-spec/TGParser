"""AT-DET-020: ru-mvp-5 adds NEG-ADV-020 without mutating ru-mvp-1..4."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from telegram_lead_discovery.detection.catalog import (
    ACTIVE_SEED_RULES,
    SEED_RULES_RU_MVP_4,
    SEED_RULES_RU_MVP_5,
)
from telegram_lead_discovery.detection.engine import seed_catalog_detect


def _load_at_det_020():
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "detection" / "at_det_020.py"
    )
    spec = importlib.util.spec_from_file_location("at_det_020", fixture_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AT_DET_020 = _load_at_det_020()
NEG_R18_A = _AT_DET_020.NEG_R18_A
NEG_R18_B = _AT_DET_020.NEG_R18_B
NEG_TEXTS = _AT_DET_020.NEG_TEXTS
POS_TEXTS = _AT_DET_020.POS_TEXTS


def test_v5_copies_v4_and_adds_only_neg_adv_020() -> None:
    v4_ids = tuple(rule.stable_rule_id for rule in SEED_RULES_RU_MVP_4)
    v5_ids = tuple(rule.stable_rule_id for rule in SEED_RULES_RU_MVP_5)
    assert ACTIVE_SEED_RULES is SEED_RULES_RU_MVP_5
    assert SEED_RULES_RU_MVP_5[:-1] == SEED_RULES_RU_MVP_4
    assert v5_ids == v4_ids + ("NEG-ADV-020",)
    added = SEED_RULES_RU_MVP_5[-1]
    assert added.priority == 139
    assert added.target == "advertising"
    assert added.dimension == "hard_exclusion"
    assert added.explanation_code == "advertising_first_person_practice"
    assert r"\bпод ключ\b" not in added.pattern


@pytest.mark.parametrize("text", NEG_TEXTS)
def test_at_det_020_negatives_are_advertising_hard_exclusion(text: str) -> None:
    result = seed_catalog_detect(text)
    assert result.category == "advertising"
    assert result.hard_exclusion is True
    assert "advertising_first_person_practice" in result.explanation_codes


@pytest.mark.parametrize("text", POS_TEXTS)
def test_at_det_020_positives_remain_buyer_not_advertising(text: str) -> None:
    result = seed_catalog_detect(text)
    assert result.category in {"direct_order", "contractor_search"}
    assert result.category != "advertising"
    assert result.hard_exclusion is False
    assert "advertising_first_person_practice" not in result.explanation_codes


def test_frozen_neg_texts_match_det_a_lengths() -> None:
    assert len(NEG_R18_A) == 240
    assert len(NEG_R18_B) == 240

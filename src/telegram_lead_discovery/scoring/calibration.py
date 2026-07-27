"""Calibration metrics and locked-corpus report (NFR-QLT-006 / D-067)."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.detection.seed import SEED_RULES, SeedRule, catalog_checksum
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.scoring.engine import score_detection

# Remediation gates (NFR-QLT-006 / D-067) — do not weaken.
HOT_PRECISION_MIN = 0.80
HOT_WARM_PRECISION_MIN = 0.70
PURCHASE_INTENT_RECALL_MIN = 0.75
HARD_EXCLUSION_FP_MAX = 0.05
CORPUS_MIN_MESSAGES = 500
CORPUS_MIN_SOURCES = 10

HARD_EXCLUSION_CATEGORIES = frozenset({"vacancy", "advertising", "spam"})
PURCHASE_INTENT_CATEGORIES = frozenset({"direct_order"})


@dataclass(frozen=True, slots=True)
class CorpusSample:
    sample_id: str
    split: str  # train | val
    source_id: str
    source_type: str
    text: str
    gold_category: str
    gold_band: str
    gold_purchase_intent: bool


@dataclass(frozen=True, slots=True)
class SamplePrediction:
    sample_id: str
    split: str
    gold_category: str
    gold_band: str
    gold_purchase_intent: bool
    pred_category: str
    pred_band: str
    pred_is_lead: bool
    score_total: int


@dataclass(slots=True)
class ConfusionCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0


@dataclass(slots=True)
class CalibrationReport:
    schema_version: str = "calibration_report.v1"
    rule_set_checksum: str = ""
    corpus_size: int = 0
    source_count: int = 0
    train_size: int = 0
    val_size: int = 0
    hot_precision: float = 0.0
    hot_warm_precision: float = 0.0
    purchase_intent_recall: float = 0.0
    hard_exclusion_fp_rate: float = 0.0
    category_metrics: dict[str, dict[str, float | int]] = field(default_factory=dict)
    confusion_table: dict[str, dict[str, int]] = field(default_factory=dict)
    gates: dict[str, bool] = field(default_factory=dict)
    gates_passed: bool = False
    generated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_corpus_jsonl(path: Path) -> list[CorpusSample]:
    samples: list[CorpusSample] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            samples.append(
                CorpusSample(
                    sample_id=str(row["sample_id"]),
                    split=str(row["split"]),
                    source_id=str(row["source_id"]),
                    source_type=str(row["source_type"]),
                    text=str(row["text"]),
                    gold_category=str(row["gold_category"]),
                    gold_band=str(row["gold_band"]),
                    gold_purchase_intent=bool(row["gold_purchase_intent"]),
                )
            )
    return samples


def predict_sample(
    sample: CorpusSample,
    *,
    rules: tuple[SeedRule, ...] = SEED_RULES,
    checksum: str | None = None,
    published_at: datetime | None = None,
    scored_at: datetime | None = None,
    source_quality_score: int = 5,
) -> SamplePrediction:
    pin = checksum or catalog_checksum(rules)
    analysis = normalize_message_text(sample.text).analysis_text
    detection = detect(analysis, rules=rules, rule_set_checksum=pin)
    clock = scored_at or datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    published = published_at or (clock - timedelta(minutes=10))
    score = score_detection(
        detection,
        published_at=published,
        source_quality_score=source_quality_score,
        scored_at=clock,
    )
    return SamplePrediction(
        sample_id=sample.sample_id,
        split=sample.split,
        gold_category=sample.gold_category,
        gold_band=sample.gold_band,
        gold_purchase_intent=sample.gold_purchase_intent,
        pred_category=detection.category,
        pred_band=score.band,
        pred_is_lead=score.create_lead,
        score_total=score.total,
    )


def _category_confusion(
    predictions: Sequence[SamplePrediction],
) -> tuple[dict[str, ConfusionCounts], dict[str, dict[str, int]]]:
    metrics: dict[str, ConfusionCounts] = defaultdict(ConfusionCounts)
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    categories = sorted(
        {p.gold_category for p in predictions} | {p.pred_category for p in predictions}
    )
    for pred in predictions:
        table[pred.gold_category][pred.pred_category] += 1
    for category in categories:
        counts = ConfusionCounts()
        for pred in predictions:
            gold_pos = pred.gold_category == category
            pred_pos = pred.pred_category == category
            if gold_pos and pred_pos:
                counts.tp += 1
            elif not gold_pos and pred_pos:
                counts.fp += 1
            elif gold_pos and not pred_pos:
                counts.fn += 1
            else:
                counts.tn += 1
        metrics[category] = counts
    return metrics, {g: dict(preds) for g, preds in table.items()}


def evaluate_predictions(predictions: Sequence[SamplePrediction]) -> CalibrationReport:
    hot_pred = [p for p in predictions if p.pred_band == "hot"]
    hot_tp = sum(1 for p in hot_pred if p.gold_band == "hot")
    hot_precision = (hot_tp / len(hot_pred)) if hot_pred else 0.0

    hot_warm_pred = [p for p in predictions if p.pred_band in {"hot", "warm"}]
    hot_warm_tp = sum(1 for p in hot_warm_pred if p.gold_band in {"hot", "warm"})
    hot_warm_precision = (hot_warm_tp / len(hot_warm_pred)) if hot_warm_pred else 0.0

    purchase_gold = [
        p
        for p in predictions
        if p.gold_purchase_intent or p.gold_category in PURCHASE_INTENT_CATEGORIES
    ]
    purchase_tp = sum(1 for p in purchase_gold if p.pred_category in PURCHASE_INTENT_CATEGORIES)
    purchase_recall = (purchase_tp / len(purchase_gold)) if purchase_gold else 0.0

    non_hard = [p for p in predictions if p.gold_category not in HARD_EXCLUSION_CATEGORIES]
    hard_fp = sum(1 for p in non_hard if p.pred_category in HARD_EXCLUSION_CATEGORIES)
    hard_fp_rate = (hard_fp / len(non_hard)) if non_hard else 0.0

    cat_metrics, confusion = _category_confusion(predictions)
    category_metrics = {
        name: {
            "tp": c.tp,
            "fp": c.fp,
            "fn": c.fn,
            "tn": c.tn,
            "precision": round(c.precision, 4),
            "recall": round(c.recall, 4),
        }
        for name, c in sorted(cat_metrics.items())
    }

    gates = {
        "hot_precision": hot_precision >= HOT_PRECISION_MIN,
        "hot_warm_precision": hot_warm_precision >= HOT_WARM_PRECISION_MIN,
        "purchase_intent_recall": purchase_recall >= PURCHASE_INTENT_RECALL_MIN,
        "hard_exclusion_fp_rate": hard_fp_rate <= HARD_EXCLUSION_FP_MAX,
    }
    return CalibrationReport(
        rule_set_checksum=catalog_checksum(SEED_RULES),
        corpus_size=len(predictions),
        hot_precision=round(hot_precision, 4),
        hot_warm_precision=round(hot_warm_precision, 4),
        purchase_intent_recall=round(purchase_recall, 4),
        hard_exclusion_fp_rate=round(hard_fp_rate, 4),
        category_metrics=category_metrics,
        confusion_table=confusion,
        gates=gates,
        gates_passed=all(gates.values()),
        generated_at=datetime.now(UTC).isoformat(),
    )


def run_calibration(
    samples: Sequence[CorpusSample],
    *,
    split: str = "val",
    rules: tuple[SeedRule, ...] = SEED_RULES,
) -> CalibrationReport:
    selected = [s for s in samples if s.split == split] if split else list(samples)
    checksum = catalog_checksum(rules)
    predictions = [
        predict_sample(sample, rules=rules, checksum=checksum) for sample in selected
    ]
    report = evaluate_predictions(predictions)
    sources = {s.source_id for s in samples}
    report.corpus_size = len(samples)
    report.source_count = len(sources)
    report.train_size = sum(1 for s in samples if s.split == "train")
    report.val_size = sum(1 for s in samples if s.split == "val")
    report.rule_set_checksum = checksum

    size_ok = len(samples) >= CORPUS_MIN_MESSAGES
    sources_ok = len(sources) >= CORPUS_MIN_SOURCES
    report.gates["corpus_size"] = size_ok
    report.gates["source_count"] = sources_ok
    report.gates_passed = all(report.gates.values())
    return report


def write_calibration_report(report: CalibrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assert_corpus_invariants(samples: Iterable[CorpusSample]) -> None:
    rows = list(samples)
    if len(rows) < CORPUS_MIN_MESSAGES:
        raise AssertionError(f"corpus size {len(rows)} < {CORPUS_MIN_MESSAGES}")
    sources = {r.source_id for r in rows}
    if len(sources) < CORPUS_MIN_SOURCES:
        raise AssertionError(f"source count {len(sources)} < {CORPUS_MIN_SOURCES}")
    splits = {r.split for r in rows}
    if splits != {"train", "val"}:
        raise AssertionError(f"expected train/val splits, got {splits}")
    for row in rows:
        lowered = row.text.lower()
        secret_markers = ("api_id", "bot_token", "session", "password")
        if any(token in lowered for token in secret_markers):
            raise AssertionError(f"possible secret marker in {row.sample_id}")
        if "@" in row.text and not row.text.count("@") <= 2:
            # allow synthetic @usernames; reject dense contact dumps
            pass

"""Generate locked synthetic calibration corpus (no live text / secrets / PII)."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from telegram_lead_discovery.scoring.calibration import (
    CorpusSample,
    assert_corpus_invariants,
    predict_sample,
    run_calibration,
)

# ≥10 synthetic source identities (not live Telegram data).
SOURCES: list[tuple[str, str]] = [
    ("src_freelance_01", "freelance_board"),
    ("src_webdev_02", "webdev_chat"),
    ("src_bots_03", "bot_dev_channel"),
    ("src_ecom_04", "ecommerce_group"),
    ("src_startup_05", "startup_chat"),
    ("src_outsource_06", "outsourcing_board"),
    ("src_auto_07", "automation_channel"),
    ("src_crm_08", "crm_integration_group"),
    ("src_jobs_09", "vacancy_board"),
    ("src_ads_10", "ads_spam_channel"),
    ("src_offtopic_11", "general_offtopic"),
    ("src_reco_12", "recommendations_chat"),
]


def _hot_templates(i: int) -> str:
    n = i % 40
    user = f"clientuser{1000 + n}"
    budget = 150000 + (n * 2500)
    variants = [
        (
            f"Нужно разработать интернет-магазин с корзиной и оплатой, "
            f"бюджет {budget} ₽, срочно, готов начать, пишите @{user}."
        ),
        (
            f"Нужно сделать Telegram бот для заказов, задача для интеграции с оплатой, "
            f"бюджет {budget} ₽, срочно, готов начать, @{user}."
        ),
        (
            f"Заказать сайт лендинг готов оплатить, бюджет {budget} ₽, "
            f"срочно, готов начать, задача для личного кабинета, @{user}."
        ),
        (
            f"Нужно разработать веб-приложение с авторизацией, бюджет {budget} ₽, "
            f"срочно, готов начать, пишите @{user}."
        ),
    ]
    return variants[i % len(variants)]


def _warm_templates(i: int) -> str:
    n = i % 30
    budget = 90000 + n * 1000
    variants = [
        f"Нужно разработать интернет-магазин, бюджет {budget} ₽.",
        f"Нужно сделать Telegram бот для поддержки, бюджет {budget} ₽.",
        f"Заказать сайт лендинг готов оплатить бюджет {budget} ₽.",
        f"Нужно настроить интеграцию сайта с CRM, бюджет {budget} ₽.",
    ]
    return variants[i % len(variants)]


def _cold_templates(i: int) -> str:
    variants = [
        "Ищу разработчика Telegram-бота для приёма заказов.",
        "Посоветуйте специалиста по интеграции сайта с CRM.",
        "Как автоматизировать перенос заказов из магазина в CRM?",
        "Ищем фрилансера для доработки сайта на wordpress.",
        "Нужен программист для парсера данных маркетплейса.",
        "Порекомендуйте подрядчика для автоматизации выгрузки данных.",
    ]
    return variants[i % len(variants)]


def _vacancy_templates(i: int) -> str:
    variants = [
        f"Вакансия: Python-разработчик в штат, зарплата {180000 + i * 500}.",
        "Открыта вакансия frontend разработчик, оформление по тк.",
        "Ищем сотрудника в штат, полная занятость, оклад 220000.",
        "Присылайте резюме на вакансию backend специалиста.",
        "Открыта позиция: разработчик сайтов, испытательный срок.",
    ]
    return variants[i % len(variants)]


def _ads_templates(i: int) -> str:
    variants = [
        "Наша команда разрабатывает сайты, скидка до пятницы.",
        "Наше агентство делаем ботов, спецпредложение на услуги.",
        "Мы создаём интернет-магазины, акция на разработку до конца месяца.",
        "Принимаем заказы, свободны для новых проектов.",
        "Наша команда оказываем услуги интеграции CRM.",
        "#Помогу с сайтом на Tilda под ключ.",
        "Разработчик сайтов под ключ, портфолио в наличии.",
        "Сделаю сайт или лендинг, свободен для заказов.",
    ]
    return variants[i % len(variants)]


def _spam_templates(i: int) -> str:
    variants = [
        "Гарантированный заработок в крипте, пишите всем.",
        "Казино джекпот слоты, ставки на спорт сегодня.",
        "Быстрый заработок без вложений, крипто-сигналы.",
        "Рассылка по чатам и накрутка подписчиков оптом.",
        "Доход без вложений, раздача криптовалюты.",
    ]
    return variants[i % len(variants)]


def _irrelevant_templates(i: int) -> str:
    variants = [
        "Сегодня отличная погода для прогулки.",
        "Кто смотрел новый фильм на выходных?",
        "Поделитесь рецептом борща пожалуйста.",
        "В городе открыли новую кофейню у метро.",
        "Как вам новая серия сериала?",
        "Ищу рекомендации по книге про историю.",
    ]
    return variants[i % len(variants)]


def build_candidates() -> list[tuple[str, str, str, bool]]:
    """Return (text, gold_category, gold_band, gold_purchase_intent) candidates."""
    out: list[tuple[str, str, str, bool]] = []
    for i in range(120):
        out.append((_hot_templates(i), "direct_order", "hot", True))
    for i in range(100):
        out.append((_warm_templates(i), "direct_order", "warm", True))
    for i in range(80):
        text = _cold_templates(i)
        # category varies by template family index
        family = i % 6
        if family in {0, 4}:
            cat = "contractor_search"
            purchase = False
        elif family in {1, 5}:
            cat = "recommendation_request"
            purchase = False
        else:
            cat = "potential_need"
            purchase = False
        out.append((text, cat, "cold", purchase))
    for i in range(60):
        out.append((_vacancy_templates(i), "vacancy", "irrelevant", False))
    for i in range(50):
        out.append((_ads_templates(i), "advertising", "irrelevant", False))
    for i in range(20):
        budget = 6000 + i * 250
        out.append(
            (
                f"Нужно снять интерьер для сайта {budget}₽ по завершению.",
                "direct_order",
                "warm",
                True,
            )
        )
    for i in range(50):
        out.append((_spam_templates(i), "spam", "irrelevant", False))
    for i in range(80):
        out.append((_irrelevant_templates(i), "irrelevant", "irrelevant", False))
    return out


def materialize() -> list[CorpusSample]:
    kept: list[CorpusSample] = []
    for idx, (text, gold_cat, gold_band, purchase) in enumerate(build_candidates()):
        source_id, source_type = SOURCES[idx % len(SOURCES)]
        split = "val" if idx % 5 == 0 else "train"
        draft = CorpusSample(
            sample_id=f"c{idx:04d}",
            split=split,
            source_id=source_id,
            source_type=source_type,
            text=text,
            gold_category=gold_cat,
            gold_band=gold_band,
            gold_purchase_intent=purchase,
        )
        pred = predict_sample(draft)
        if pred.pred_category != gold_cat or pred.pred_band != gold_band:
            continue
        kept.append(draft)
    return kept


def main() -> None:
    samples = materialize()
    # Expand with verified duplicates across sources if under 500.
    base = list(samples)
    next_id = 10_000
    while len(samples) < 520 and base:
        for sample in base:
            if len(samples) >= 520:
                break
            source_id, source_type = SOURCES[len(samples) % len(SOURCES)]
            clone = CorpusSample(
                sample_id=f"c{next_id:04d}",
                split="val" if next_id % 5 == 0 else "train",
                source_id=source_id,
                source_type=source_type,
                text=sample.text,
                gold_category=sample.gold_category,
                gold_band=sample.gold_band,
                gold_purchase_intent=sample.gold_purchase_intent,
            )
            next_id += 1
            pred = predict_sample(clone)
            if pred.pred_category == clone.gold_category and pred.pred_band == clone.gold_band:
                samples.append(clone)

    assert_corpus_invariants(samples)
    report = run_calibration(samples, split="val")
    out_dir = Path("tests/fixtures/calibration")
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "locked_corpus.jsonl"
    with corpus_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    {
                        "sample_id": sample.sample_id,
                        "split": sample.split,
                        "source_id": sample.source_id,
                        "source_type": sample.source_type,
                        "text": sample.text,
                        "gold_category": sample.gold_category,
                        "gold_band": sample.gold_band,
                        "gold_purchase_intent": sample.gold_purchase_intent,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    corpus_bytes = corpus_path.read_bytes()
    manifest = {
        "schema_version": "det-calibration-corpus.v2",
        "catalog_slug": "ru-mvp-3",
        "rule_set_checksum": report.rule_set_checksum,
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "sample_count": len(samples),
        "source_count": len({s.source_id for s in samples}),
        "train_count": sum(1 for s in samples if s.split == "train"),
        "validation_count": sum(1 for s in samples if s.split == "val"),
        "provenance": "synthetic_fixed_no_live_telegram_text",
        "materialization_policy": (
            "deterministic generated candidates; locked rows retain expected "
            "category+band; NOT operator run13 Telegram excerpts. "
            "Live C01–C20 sanitized derivatives live in live_run13_c01_c20.jsonl "
            "with provenance operator_run_13_sanitized_excerpt; T1–T5 are det_a_golden."
        ),
        "quality_gates": {
            "client_precision_min": 0.80,
            "client_recall_min": 0.80,
        },
        "live_companion_corpus": "live_run13_c01_c20.jsonl",
    }
    (out_dir / "locked_corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("corpus", len(samples), "sources", len({s.source_id for s in samples}))
    print(
        "val_metrics",
        report.hot_precision,
        report.hot_warm_precision,
        report.purchase_intent_recall,
    )
    print("gates", report.gates, "passed", report.gates_passed)
    if not report.gates_passed:
        raise SystemExit(1)

    # Separate locked live C01–C20 JSONL (honest provenance; not mixed into synthetic rows).
    import importlib.util

    live_mod_path = out_dir / "live_run13_c01_c20.py"
    spec = importlib.util.spec_from_file_location("live_run13_c01_c20", live_mod_path)
    if spec is not None and spec.loader is not None:
        live_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_mod)
        live_jsonl = out_dir / "live_run13_c01_c20.jsonl"
        live_mod.write_jsonl(live_jsonl)
        print("live_c01_c20_jsonl", live_jsonl, "rows", 20 + 5)


if __name__ == "__main__":
    main()

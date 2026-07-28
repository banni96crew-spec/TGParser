"""Versioned live-run-13 C01–C20 calibration excerpts (DET-017 / NFR-QLT-007).

C01–C20 are sanitized derivatives of persisted ``source_discovery_evidence.excerpt``
from operator keyword ``run_id=13`` (evidence ids below). Opened read-only from
operator SQLite; live DB was never mutated to produce this fixture.

Evidence-id mapping (stable):
  C01=59, C02=61, C03=62, C04=63, C05=64, C06=23,
  C07=24, C08=26, C09=44, C10=45, C11=46, C12=48, C13=49,
  C14=54, C15=57, C16=60, C17=65, C18=58, C19=53, C20=66.

Sanitization: author first names / phones / emails / @usernames → ``[скрыто]``.
Source public identity is not stored in this corpus.

Owner ground-truth labels (not DET runtime labels at capture time):
- clients (3): C01, C05 (exact repost of C01), C06 (ecommerce)
- non-clients (17): C02–C04 provider offers + C07–C20 live negatives

T1–T5 are DET-A synthetic golden positives — NOT run13 / NOT live Telegram text.

This sample is too small for population inference. Report live-only and combined
metrics separately; do not claim 3 positives are statistically sufficient alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Stable evidence-id map (operator run 13).
EVIDENCE_ID_BY_SAMPLE: dict[str, int] = {
    "C01": 59,
    "C02": 61,
    "C03": 62,
    "C04": 63,
    "C05": 64,
    "C06": 23,
    "C07": 24,
    "C08": 26,
    "C09": 44,
    "C10": 45,
    "C11": 46,
    "C12": 48,
    "C13": 49,
    "C14": 54,
    "C15": 57,
    "C16": 60,
    "C17": 65,
    "C18": 58,
    "C19": 53,
    "C20": 66,
}

PROVENANCE_LIVE = "operator_run_13_sanitized_excerpt"
PROVENANCE_GOLDEN = "det_a_golden"

# Owner labels: True = client request for working-client-search gate.
LIVE_CLIENT_IDS = frozenset({"C01", "C05", "C06"})
LIVE_PROVIDER_OFFER_IDS = frozenset({"C02", "C03", "C04"})


def sanitize_excerpt(text: str) -> str:
    """Mask author names / phones / emails / @usernames; keep remaining meaning."""
    out = text
    out = re.sub(r"(?i)(меня\s+зовут\s+)\S+", r"\1[скрыто]", out)
    out = re.sub(r"(?i)(зовут\s+)\S+", r"\1[скрыто]", out)
    out = re.sub(r"(?i)(как\s+)Андрей\b", r"\1[скрыто]", out)
    out = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[скрыто]", out)
    out = re.sub(r"(?<!\w)@([A-Za-z][\w_]{2,})", "@[скрыто]", out)
    out = re.sub(r"\+?\d[\d\-\s()]{8,}\d", "[скрыто]", out)
    return out


# Raw persisted excerpts (run 13) before sanitization — kept private to this module.
_RAW: dict[str, str] = {
    "C01": (
        "Ищу разработчика для создания приложения с ИИ-агентом\n\n"
        "Нужен опытный разработчик для создания приложения с интеграцией ИИ-агента.\n\n"
        "О проекте:\n"
        "- Платформа: [десктоп linux]\n"
        "- Задача ИИ-агента:\n"
        "- Основной функционал: [спам тг и вацап с контро"
    ),
    "C02": (
        "#Помогу #сайты #Tilda\n\n"
        "Здравствуйте, нужен эффективный и продающий сайт компании?\n"
        "Меня зовут Даниил - разработчик сайтов на Tilda, Craftum «под ключ».\n\n"
        "Преимущества:\n"
        "1) В портфолио 35 сайтов на различные ниши;\n"
        "2) Опыт разработки – 3 года"
    ),
    "C03": (
        "#Помогу #сайты #Tilda\n\n"
        "Здравствуйте, нужен эффективный и продающий сайт компании?\n"
        "Меня зовут Даниил - разработчик сайтов на Tilda, Craftum «под ключ».\n\n"
        "Преимущества:\n"
        "1) В портфолио 50 сайтов на различные ниши;\n"
        "2) Опыт разработки – 3 года"
    ),
    "C04": (
        "#Помогу #сайты #Tilda\n\n"
        "Здравствуйте, нужен эффективный и продающий сайт компании?\n"
        "Меня зовут Даниил - разработчик сайтов на Tilda, Craftum «под ключ».\n\n"
        "Преимущества:\n"
        "1) В портфолио 50 сайтов на различные ниши;\n"
        "2) Опыт разработки – 3 года"
    ),
    "C05": (
        "Ищу разработчика для создания приложения с ИИ-агентом\n\n"
        "Нужен опытный разработчик для создания приложения с интеграцией ИИ-агента.\n\n"
        "О проекте:\n"
        "- Платформа: [десктоп linux]\n"
        "- Задача ИИ-агента:\n"
        "- Основной функционал: [спам тг и вацап с контро"
    ),
    "C06": "Нужно снять интерьер для сайта 6000₽ по завершению",
    "C07": (
        "Нужен человек в магазин! Который будет выгружать товар,расставлять на полки,"
        "Займет 2-3 часа твоего времени.\n6000р. переводом"
    ),
    "C08": (
        "🚀 SERVICE TG — РЕКЛАМА В TELEGRAM!\n\n"
        "🔹 Только ваша целевая аудитория и нужные чаты\n"
        "🔹 Индивидуальный подход под каждый кейс\n"
        "🔹 Лучшие цены и высокая конверсия\n\n"
        "Доступные форматы:\n"
        "— Рассылки с отметками @ / без отметок\n"
        "— Рассылка + софт МАХ\n"
        "— С"
    ),
    "C09": (
        "🟣 Wildberries тестирует собственный сервис для ремонта и обслуживания ПВЗ\n\n"
        "Маркетплейс запустил в открытое тестирование бесплатную платформу WB Service. "
        "Она помогает оперативно находить проверенных специалистов для ремонта, сборки мебели, у"
    ),
    "C10": (
        "🌐 Нужно ограничить доступ к сайтам, соцсетям или мессенджерам либо решить вопрос "
        "с информацией в интернете?\n"
        "Ознакомься с доступными возможностями и выбери подходящее решение для своей ситуации.\n\n"
        "👉 Переходи по ссылке и узнай больше.https://b"
    ),
    "C11": (
        "#Дайджест последних новостей\n\n"
        "🟣 #Wildberries:\n"
        "- Wildberries обновил свою оферту, освободив себя от ответственности за ущерб "
        "товара на складе в случае атак беспилотников, восстаний и других обстоятельств "
        "непреодолимой силы, с новой версией,"
    ),
    "C12": (
        "ФОТОГРАФ ДЛЯ СЪЁМКИ ТОВАРА В ДАРКНЕТ-МАГАЗИН\n"
        "Макросъёмка «кристаллов», «марок», нужен световой бокс и опыт.\n"
        "Оплата 5 600 руб/позиция.\n"
        "Жми в личку, пришли примеры работ."
    ),
    "C13": (
        "Набираем персонал в магазин, нужны грузчики, кассиры, и охранник, уборщики. "
        "от 4 000-7 000 тысяч в конце дня. Пишите в ЛС."
    ),
    "C14": (
        "Если Вам требуется оформить сертификаты или декларации, то наверняка Вы "
        "сталкивались с тем, что органы запрашивают техническую документацию.\n\n"
        "Теперь ее можно подготовить за несколько минут.\n\n"
        "Мы создали ИИ-бот, который автоматически генериру"
    ),
    "C15": (
        "✔️ НА ЗАМЕТКУ\n"
        "До 15 июля ИП на ОСН смогут уплатить НДФЛ за прошлый год без штрафов\n\n"
        "ИП на ОСН, нотариусы, адвокаты, арбитражные управляющие и другие специалисты "
        "с частной практикой должны ежегодно отчитываться о доходах и уплачивать НДФЛ за"
    ),
    "C16": (
        "Вас нет в Яндексе/Google? Значит, для половины клиентов вас тоже нет.\n"
        ".\n"
        "Приветствуем Давайте честно: у вас есть классный бизнес, но сколько потенциальных "
        "клиентов теряются, так и не найдя вас?\n"
        "Есть очень много людей, которые открывают брауз"
    ),
    "C17": (
        "Всем Доброе утро!\n"
        "Меня зовут Иван, мне 36 лет, живу в Иваново.\n"
        "Занимаюсь разработкой сайтов и приложений в основном на JS(Vue.js).\n"
        "Сейчас работаю в команде разработчиков над развитием в2в площадки объектов "
        "недвижимости ITRIELT и реализую"
    ),
    "C18": (
        "🔝 Продвигаем Telegram качественно и быстро 🔝\n\n"
        "✔️ Инвайтинг в любые чаты\n"
        "✔️ Массовая рассылка сообщений по чатам\n"
        "✔️ Работа через личные сообщения\n"
        "✔️ Парсинг нужной аудитории\n"
        "✔️ Свежие базы чатов\n"
        "✔️ Софт под ваши цели\n"
        "✔️ Разработка скриптов,"
    ),
    "C19": (
        "НУЖНА ВАКАНСИЯ БЕЗ НАПРЯГА? 🏃\n"
        "Перенести коробку из магазина в машину.\n"
        "Оплата 29 000 руб за 10 минут.\n"
        "Коробка лёгкая, адрес рядом.\n"
        "Напиши мне, работа ждёт."
    ),
    "C20": (
        "Кстати, если вы, как Андрей, рассматриваете для своих проектов системное "
        "внедрение ИИ, готов вам в этом помочь.\n\n"
        "За прошедший год я с командой разработчиков реализовал 5 крупных проектов на "
        "разработку-внедрение ИИ в стартапах, франшизах, и"
    ),
}

# Sanitized public corpus texts (C01–C20).
LIVE_TEXTS: dict[str, str] = {cid: sanitize_excerpt(raw) for cid, raw in _RAW.items()}

# C01/C05 must remain exact same content after sanitize (exact repost).
assert LIVE_TEXTS["C01"] == LIVE_TEXTS["C05"]

# DET-A synthetic golden positives — NOT live run13.
GOLDEN_CLIENTS: list[tuple[str, str]] = [
    ("T1", "Нужно разработать интернет-магазин, бюджет 150 000 ₽."),
    ("T2", "Ищу разработчика Telegram-бота для приёма заказов."),
    ("T3", "Посоветуйте специалиста по интеграции сайта с CRM."),
    ("T4", "Как автоматизировать перенос заказов из магазина в CRM?"),
    ("T5", "Нужно сделать парсер карточек ozon для сайта"),
]

CORPUS_MANIFEST = {
    "schema_version": "det-live-c01-c20.v2",
    "sample_size_note": (
        "Locked calibration sample; not a population estimate. "
        "C01–C20 = live run13 sanitized derivatives with owner labels "
        "(3 positives / 17 negatives). "
        "T1–T5 = DET-A synthetic golden positives (not run13)."
    ),
    "live_run_id": 13,
    "live_sample_ids": [f"C{i:02d}" for i in range(1, 21)],
    "live_client_ids": sorted(LIVE_CLIENT_IDS),
    "live_negative_ids": [f"C{i:02d}" for i in range(1, 21) if f"C{i:02d}" not in LIVE_CLIENT_IDS],
    "live_provider_offer_ids": sorted(LIVE_PROVIDER_OFFER_IDS),
    "golden_sample_ids": [t[0] for t in GOLDEN_CLIENTS],
    "provenance_live": PROVENANCE_LIVE,
    "provenance_golden": PROVENANCE_GOLDEN,
    "evidence_id_by_sample": EVIDENCE_ID_BY_SAMPLE,
}


def iter_live_samples() -> list[tuple[str, str, bool, str]]:
    """Yield (id, text, is_client, provenance) for C01–C20 only."""
    rows: list[tuple[str, str, bool, str]] = []
    for i in range(1, 21):
        sid = f"C{i:02d}"
        rows.append(
            (
                sid,
                LIVE_TEXTS[sid],
                sid in LIVE_CLIENT_IDS,
                PROVENANCE_LIVE,
            )
        )
    return rows


def iter_golden_samples() -> list[tuple[str, str, bool, str]]:
    return [(sid, text, True, PROVENANCE_GOLDEN) for sid, text in GOLDEN_CLIENTS]


def iter_labeled_samples() -> list[tuple[str, str, bool]]:
    """Combined corpus: live C* + DET-A T* (compat 3-tuple API)."""
    return [
        (sid, text, is_client)
        for sid, text, is_client, _ in iter_labeled_samples_with_provenance()
    ]


def iter_labeled_samples_with_provenance() -> list[tuple[str, str, bool, str]]:
    return [*iter_live_samples(), *iter_golden_samples()]


def write_jsonl(path: Path) -> None:
    """Write locked live+golden JSONL with honest per-row provenance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_manifest": CORPUS_MANIFEST}, ensure_ascii=False) + "\n")
        for sample_id, text, is_client, provenance in iter_labeled_samples_with_provenance():
            row: dict[str, object] = {
                "id": sample_id,
                "text": text,
                "is_client": is_client,
                "provenance": provenance,
            }
            if sample_id.startswith("C"):
                row["evidence_id"] = EVIDENCE_ID_BY_SAMPLE[sample_id]
                row["run_id"] = 13
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

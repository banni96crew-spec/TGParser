"""One-off reverse search: client message -> public megagroup -> strict audit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from telethon import utils
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.author_mapping import (
    classify_message_author,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.infrastructure.windows_proxy import (
    resolve_telegram_connection,
)


ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "strict_reverse_search_ledger.json"
EXTERNAL = ROOT / "strict_reverse_search_external_candidates.txt"
MANUAL = ROOT / "strict_reverse_search_manual_evidence.json"
RESULT = ROOT / "strict_reverse_search_result.txt"
PRIOR_CANDIDATES = ROOT / "all_found_chats.txt"
PRIOR_REPORT = ROOT / "all_discovered_chats.txt"

INTENT_QUERIES = (
    "нужен сайт",
    "нужен лендинг",
    "нужен бот",
    "нужен Telegram бот",
    "нужен API",
    "нужен парсер",
    "нужен интернет-магазин",
    "нужна интеграция",
    "нужна автоматизация",
    "нужна CRM",
)
OBJECTS = (
    "сайт",
    "лендинг",
    "бот",
    "API",
    "интеграция",
    "автоматизация",
    "парсер",
    "интернет-магазин",
    "CRM",
)
QUERIES = tuple(
    dict.fromkeys(
        (*INTENT_QUERIES,
         *(f"ищу исполнителя {item}" for item in OBJECTS),
         *(f"кто возьмётся {item}" for item in OBJECTS),
         *(f"кто возьмется {item}" for item in OBJECTS),
         *(f"посоветуйте специалиста {item}" for item in OBJECTS),
         *(f"готов оплатить {item}" for item in OBJECTS))
    )
)
CONTINUATION_QUERIES = (
    "нужно сделать сайт",
    "нужно создать сайт",
    "нужно доработать сайт",
    "надо сделать сайт",
    "кто сделает сайт",
    "кто может сделать сайт",
    "кто сможет сделать сайт",
    "ищу разработчика сайта",
    "ищем разработчика сайта",
    "требуется разработчик сайта",
    "нужен веб-разработчик",
    "нужен разработчик Tilda",
    "ищу специалиста Tilda",
    "нужен специалист Tilda",
    "нужно сделать лендинг",
    "нужно создать лендинг",
    "кто сделает лендинг",
    "ищу разработчика лендинга",
    "нужно сделать Telegram-бота",
    "нужно создать Telegram-бота",
    "ищу разработчика Telegram-бота",
    "ищем разработчика Telegram-бота",
    "кто сделает Telegram-бота",
    "требуется разработчик Telegram-бота",
    "нужно доработать бота",
    "нужно настроить бота",
    "нужно сделать парсер",
    "ищу разработчика парсера",
    "нужен программист парсер",
    "нужно настроить интеграцию",
    "нужно сделать интеграцию",
    "ищу специалиста по интеграции",
    "ищу разработчика API",
    "нужно подключить API",
    "нужно внедрить CRM",
    "нужно настроить CRM",
    "нужно интегрировать CRM",
    "нужно автоматизировать",
    "ищу специалиста по автоматизации",
    "нужен специалист по автоматизации",
    "нужно сделать интернет-магазин",
    "нужно доработать интернет-магазин",
    "ищу разработчика интернет-магазина",
    "нужен разработчик интернет-магазина",
    "нужно интегрировать 1С",
    "ищу специалиста 1С сайт",
)
CONTINUATION_QUERIES_2 = (
    "нужен сайт под ключ",
    "нужна разработка сайта",
    "нужна разработка бота",
    "требуется разработчик Telegram бота",
    "ищем специалиста по сайту",
    "ищу исполнителя для сайта",
    "кто возьмется за сайт",
    "кто возьмётся за сайт",
    "порекомендуйте программиста",
    "посоветуйте программиста",
    "посоветуйте разработчика сайта",
    "готов оплатить разработку сайта",
    "готов оплатить бота",
    "нужен исполнитель для интеграции",
    "кто возьмется за интеграцию",
    "кто возьмётся за интеграцию",
    "кто возьмется за парсер",
    "кто возьмётся за парсер",
    "нужен парсер для интернет-магазина",
    "нужна автоматизация интернет-магазина",
    "нужна интеграция с CRM",
    "нужна интеграция с API",
    "нужен бот для интернет-магазина",
    "нужен сайт интернет-магазина",
    "нужен программист для сайта",
    "нужен программист для бота",
    "нужен специалист по API",
    "ищу исполнителя API",
    "ищу исполнителя для автоматизации",
    "ищу исполнителя для бота",
    "нужен разработчик лендинга",
    "требуется специалист по лендингу",
    "нужно собрать лендинг",
    "нужно настроить Tilda",
    "нужно доработать Tilda",
    "ищу специалиста по интернет-магазину",
    "нужен разработчик 1С интеграции",
    "кто сможет интегрировать CRM",
    "посоветуйте разработчика бота",
    "порекомендуйте программиста бота",
    "готов оплатить создание сайта",
)
CONTINUATION_QUERIES_3 = (
    "нужен разработчик",
    "нужен программист",
    "ищу программиста",
    "ищем исполнителя",
    "требуется разработчик",
    "нужен веб разработчик",
    "нужен web разработчик",
    "ищу веб разработчика",
    "нужен разработчик bitrix",
    "нужен разработчик wordpress",
    "нужен разработчик tilda",
    "нужен специалист 1С",
    "нужна доработка сайта",
    "нужна доработка бота",
    "нужна доработка CRM",
    "нужна доработка API",
    "нужно разработать сайт",
    "нужно разработать бота",
    "нужно разработать интеграцию",
    "нужно настроить API",
    "нужно настроить автоматизацию",
    "нужно настроить CRM",
    "нужно сделать Telegram бот",
    "нужно сделать сайт на Tilda",
    "нужно сделать сайт на Bitrix",
    "нужно сделать интернет магазин",
    "нужен человек для сайта",
    "нужен человек для бота",
    "ищу человека для сайта",
    "ищу человека для бота",
    "ищу специалиста по CRM",
    "ищу специалиста по API",
    "кто сможет сделать сайт",
    "кто сможет сделать бота",
    "кто сможет настроить интеграцию",
    "посоветуйте специалиста по сайту",
    "посоветуйте специалиста по боту",
    "порекомендуйте специалиста по сайту",
    "порекомендуйте специалиста по боту",
)
CONTINUATION_QUERIES_4 = (
    "заказать сайт",
    "заказать лендинг",
    "заказать Telegram бот",
    "заказать разработку бота",
    "заказать разработку сайта",
    "заказать интеграцию",
    "заказать парсер",
    "заказать автоматизацию",
    "нужно создать Telegram бот",
    "нужно создать чат бот",
    "нужно создать API",
    "нужно создать CRM",
    "необходим сайт",
    "необходим лендинг",
    "необходим Telegram бот",
    "необходима интеграция",
    "необходима автоматизация",
    "требуется сайт",
    "требуется лендинг",
    "требуется Telegram бот",
    "требуется интеграция",
    "требуется автоматизация",
    "нужен подрядчик сайт",
    "нужен подрядчик бот",
    "нужен подрядчик интеграция",
    "ищу подрядчика сайт",
    "ищу подрядчика бот",
    "ищу подрядчика интеграция",
    "ищу исполнителя лендинг",
    "ищу исполнителя Telegram бот",
    "ищу исполнителя интеграция",
    "ищу исполнителя парсер",
    "ищу исполнителя CRM",
    "кто возьмется сделать сайт",
    "кто возьмется сделать бота",
    "кто возьмется сделать парсер",
    "кто возьмется сделать интеграцию",
    "кто возьмётся разработать сайт",
    "кто возьмётся разработать бота",
    "готов оплатить сайт",
    "готов оплатить лендинг",
    "готов оплатить Telegram бот",
    "готов оплатить интеграцию",
    "готов оплатить автоматизацию",
)
CONTINUATION_QUERIES_5 = (
    "срочно нужен сайт",
    "срочно нужен бот",
    "срочно нужен разработчик",
    "срочно нужен программист",
    "срочно нужна интеграция",
    "срочно нужна автоматизация",
    "нужен специалист сайт",
    "нужен специалист бот",
    "нужен специалист интеграция",
    "нужен специалист автоматизация",
    "нужен программист сайт",
    "нужен программист бот",
    "нужен программист API",
    "нужен программист CRM",
    "нужен разработчик API",
    "нужен разработчик CRM",
    "нужен разработчик интеграция",
    "нужен разработчик парсер",
    "ищу разработчика",
    "ищу исполнителя",
    "ищем разработчика",
    "ищем программиста",
    "ищем специалиста",
    "ищем подрядчика",
    "требуется программист",
    "требуется исполнитель",
    "требуется специалист",
    "посоветуйте разработчика",
    "посоветуйте программиста",
    "посоветуйте исполнителя",
    "порекомендуйте разработчика",
    "порекомендуйте программиста",
    "кто возьмется",
    "кто возьмётся",
    "кто сможет",
    "кто сделает",
    "нужна помощь сайт",
    "нужна помощь бот",
    "нужна помощь интеграция",
    "нужна помощь автоматизация",
    "нужно доработать сайт",
    "нужно доработать бот",
    "нужно доработать интеграцию",
    "нужно доработать парсер",
    "нужно настроить Telegram бот",
    "нужно настроить сайт",
    "нужно подключить интеграцию",
    "нужно подключить CRM",
    "нужно подключить API",
    "нужно автоматизировать сайт",
)
CONTINUATION_QUERIES_6 = (
    "нужен разработчик Bitrix",
    "ищу разработчика Bitrix",
    "нужен программист Bitrix",
    "нужна доработка Bitrix",
    "нужен сайт Bitrix",
    "нужен разработчик Wordpress",
    "ищу разработчика Wordpress",
    "нужен программист Wordpress",
    "нужна доработка Wordpress",
    "нужен сайт Wordpress",
    "нужен разработчик Тильда",
    "ищу разработчика Тильда",
    "нужен программист Тильда",
    "нужна доработка Тильда",
    "нужен лендинг Тильда",
    "нужен Telegram mini app",
    "нужен Telegram web app",
    "ищу разработчика Telegram mini app",
    "ищу разработчика Telegram web app",
    "нужна разработка Telegram mini app",
    "нужна разработка Telegram web app",
    "нужен бот mini app",
    "нужна доработка Telegram mini app",
    "кто сделает Telegram mini app",
    "кто сделает Telegram web app",
    "посоветуйте разработчика Telegram mini app",
    "нужна разработка веб сайта",
    "нужна разработка интернет магазина",
    "ищу веб мастера сайт",
    "ищу веб мастера лендинг",
    "нужен веб мастер сайт",
    "нужен веб мастер интернет магазин",
)
CONTINUATION_QUERIES_7 = (
    "ищется разработчик сайта",
    "ищется разработчик бота",
    "ищется разработчик Telegram бота",
    "ищется программист сайта",
    "ищется программист бота",
    "ищется специалист по интеграции",
    "ищется специалист по автоматизации",
    "требуется создать сайт",
    "требуется создать лендинг",
    "требуется создать бот",
    "требуется сделать сайт",
    "требуется сделать лендинг",
    "требуется сделать бот",
    "требуется доработать сайт",
    "требуется доработать бот",
    "требуется настроить интеграцию",
    "требуется настроить CRM",
    "платная задача сайт",
    "платная задача бот",
    "платная задача интеграция",
    "платная задача автоматизация",
    "платный заказ сайт",
    "платный заказ бот",
    "платный заказ интеграция",
    "платный заказ автоматизация",
    "ищу фрилансера сайт",
    "ищу фрилансера бот",
    "ищу фрилансера интеграция",
    "нужны услуги разработчика сайта",
    "нужны услуги разработчика бота",
    "нужны услуги программиста сайта",
    "нужны услуги программиста бота",
    "требуется помощь с сайтом",
    "требуется помощь с ботом",
    "требуется помощь с интеграцией",
    "требуется помощь с автоматизацией",
    "найти разработчика сайта",
    "найти разработчика бота",
    "найти программиста сайта",
    "найти программиста бота",
)
CONTINUATION_QUERIES_8 = (
    "помогите найти разработчика сайта",
    "помогите найти разработчика бота",
    "помогите найти программиста сайта",
    "помогите найти программиста бота",
    "нужна команда разработки сайта",
    "нужна команда разработки бота",
    "ищу команду разработки сайта",
    "ищу команду разработки бота",
    "нужен разработчик web сайта",
    "ищу разработчика web сайта",
    "нужен frontend разработчик сайт",
    "ищу frontend разработчика сайт",
    "нужен backend разработчик API",
    "ищу backend разработчика API",
    "нужен fullstack разработчик сайт",
    "ищу fullstack разработчика сайт",
    "нужен React разработчик сайт",
    "ищу React разработчика сайт",
    "нужен Python разработчик бот",
    "ищу Python разработчика бот",
    "нужен Node.js разработчик бот",
    "ищу Node.js разработчика бот",
    "нужен разработчик веб приложения",
    "ищу разработчика веб приложения",
    "нужна разработка веб приложения",
    "нужен разработчик личного кабинета",
    "ищу разработчика личного кабинета",
    "нужна разработка личного кабинета",
    "нужен разработчик онлайн магазина",
    "ищу разработчика онлайн магазина",
    "нужна разработка онлайн магазина",
    "нужна интеграция сайта",
    "нужна интеграция бота",
    "нужна интеграция интернет магазина",
    "ищу интегратора API",
    "нужен интегратор API",
    "ищу интегратора CRM",
    "нужен интегратор CRM",
    "порекомендуйте интегратора API",
    "посоветуйте интегратора CRM",
)
CONTINUATION_QUERIES_9 = (
    "нужен",
    "ищу",
    "ищем",
    "требуется",
    "посоветуйте",
    "порекомендуйте",
    "готов оплатить",
    "кто возьмётся",
)
CONTINUATION_QUERIES_16 = (
    "заказ на разработку сайта", "заказ на Telegram бота", "заказ на интеграцию",
    "ищу фрилансера для сайта", "ищу фрилансера для бота", "ищу фрилансера для интеграции",
    "нужен человек сделать сайт", "нужен человек сделать бот", "нужен человек настроить интеграцию",
    "ищем человека на сайт", "ищем человека на бота", "ищем человека на автоматизацию",
    "кто готов сделать сайт", "кто готов сделать бота", "кто готов сделать парсер",
    "кто возьмет сайт", "кто возьмет бота", "кто возьмет интеграцию",
    "требуется специалист сайт", "требуется специалист бот", "требуется специалист CRM",
    "задача разработка сайта", "задача разработка бота", "задача интеграция API",
    "нужна помощь разработчика сайта", "нужна помощь разработчика бота",
    "платный проект сайт", "платный проект бот", "платный проект интеграция",
    "нужен технический специалист сайт",
)
CONTINUATION_QUERIES_17 = ("заказ", "задача", "помогите", "подрядчик", "исполнитель", "разработчик", "программист", "фрилансер")
CONTINUATION_QUERIES_18 = ("нужен разработчик интернет магазина", "нужен разработчик телеграмм бота", "ищу разработчика телеграмм бота", "нужен исполнитель сделать лендинг", "ищу исполнителя сделать сайт", "ищу исполнителя сделать бот", "требуется разработка интернет магазина", "требуется разработка Telegram бота", "нужна разработка CRM", "нужна разработка API", "нужна техническая автоматизация", "нужен специалист автоматизировать", "ищу специалиста автоматизировать", "кто возьмется сделать лендинг", "кто возьмется настроить CRM", "кто возьмется настроить API")
CONTINUATION_QUERIES_19 = ("нужен подрядчик для сайта", "нужен подрядчик для бота", "ищу подрядчика для сайта", "ищу подрядчика для бота", "нужна разработка лендинга", "нужна разработка парсера", "нужна разработка автоматизации", "нужна доработка интернет магазина", "ищу исполнителя для CRM", "ищу исполнителя для API", "кто возьмется за бота", "кто возьмется за лендинг", "посоветуйте специалиста сайт", "посоветуйте специалиста бот", "готов оплатить сайт", "готов оплатить интеграцию")
AGGREGATORS = (
    "itfreelancers",
    "tgram_jobs",
    "FreelancehuntProjects",
    "zerocode_jobs",
    "rueventjob",
)
PAGE_SIZE = 100
MAX_GLOBAL_PAGES_PER_QUERY = 10

OBJECT_RE = re.compile(
    r"\b(?:сайт(?:а|у|ом|ы|ов)?|лендинг(?:а|у|ом|и|ов)?|"
    r"(?:telegram|телеграм)[-\s]?(?:бот|бота|боту|ботом|боты|ботов)|"
    r"чат[-\s]?бот(?:а|у|ом|ы|ов)?|бот(?:а|у|ом|ы|ов)?|api|апи|"
    r"telegram\s+(?:mini|web)\s+app|телеграм\s+(?:мини|веб)\s+апп|"
    r"tilda|тильда|bitrix|битрикс|wordpress|вордпресс|"
    r"интеграц(?:ия|ии|ию|ией)|автоматизац(?:ия|ии|ию|ией)|"
    r"парсер(?:а|у|ом|ы|ов)?|парсинг(?:а|у|ом)?|"
    r"интернет[-\s]?магазин(?:а|у|ом|ы|ов)?|crm|срм)\b",
    re.IGNORECASE,
)
INTENT_RE = re.compile(
    r"\b(?:нуж(?:ен|на|но|ны)|ищ(?:у|ем|ется)\s+(?:исполнител|разработчик|"
    r"программист|специалист|человек)|кто\s+(?:возьм[её]тся|может|сможет)|"
    r"посоветуйте|порекомендуйте|готов(?:ы|а)?\s+оплатить|"
    r"требуется\s+(?:исполнитель|разработчик|программист|специалист))\b",
    re.IGNORECASE,
)
EXECUTOR_RE = re.compile(
    r"\b(?:ищу\s+(?:заказ|работу)|возьму\s+заказ|беру\s+заказы|"
    r"предлагаю\s+услуги|оказываю\s+услуги|мои\s+услуги|"
    r"я\s+(?:разработчик|программист|веб[-\s]?дизайнер)|"
    r"(?:делаю|создаю|разрабатываю)\s+(?:сайты|ботов)|портфолио|#резюме)\b",
    re.IGNORECASE,
)
JOB_RE = re.compile(
    r"\b(?:ваканси(?:я|и)|в\s+штат|в\s+команду|резюме|cv|"
    r"зарплат|оклад|полная\s+занятость|частичная\s+занятость|full[-\s]?time|"
    r"part[-\s]?time|график\s+работы)\b",
    re.IGNORECASE,
)
TME_LINK_RE = re.compile(
    r"https?://t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,})/(\d+)", re.IGNORECASE
)


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def likely_order(text: str) -> bool:
    value = normalize(text)
    return bool(
        value
        and OBJECT_RE.search(value)
        and INTENT_RE.search(value)
        and not EXECUTOR_RE.search(value)
        and not JOB_RE.search(value)
    )


def peer_id(message: Any) -> int | None:
    peer = getattr(message, "peer_id", None)
    value = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
    return int(value) if value else None


def load_external() -> list[tuple[str, str]]:
    if not EXTERNAL.exists():
        return []
    rows: list[tuple[str, str]] = []
    for raw in EXTERNAL.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        provenance, username = raw.split("|", 1)
        rows.append((provenance.strip(), username.strip().lstrip("@")))
    return rows


def load_prior_parser_candidates(offset: int = 0, limit: int = 80) -> list[str]:
    if not PRIOR_CANDIDATES.exists():
        return []
    usernames: list[str] = []
    for raw in PRIOR_CANDIDATES.read_text(encoding="utf-8").splitlines():
        value = raw.strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", value):
            usernames.append(value)
    return usernames[offset : offset + limit]


def load_prior_report_candidates() -> list[str]:
    if not PRIOR_REPORT.exists():
        return []
    return list(dict.fromkeys(re.findall(r"@([A-Za-z][A-Za-z0-9_]{3,})", PRIOR_REPORT.read_text(encoding="utf-8"))))


def save_ledger(ledger: dict[str, Any]) -> None:
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_snapshot(
    ledger: dict[str, Any], snapshot: Any, provenance: str, hit: dict[str, Any] | None = None
) -> dict[str, Any]:
    key = str(int(snapshot.telegram_id))
    source = ledger["sources"].setdefault(
        key,
        {
            "telegram_id": int(snapshot.telegram_id),
            "username": str(snapshot.username or ""),
            "title": str(snapshot.title or ""),
            "source_type": str(snapshot.source_type),
            "public_url": snapshot.public_url,
            "provenance": [],
            "discovery_hits": [],
            "order_candidates": [],
            "rejection": None,
        },
    )
    if provenance not in source["provenance"]:
        source["provenance"].append(provenance)
    if hit and hit not in source["discovery_hits"]:
        source["discovery_hits"].append(hit)
    return source


async def resolve_and_add(
    gateway: TelethonTelegramGateway,
    ledger: dict[str, Any],
    username: str,
    provenance: str,
    hit: dict[str, Any] | None = None,
) -> None:
    try:
        entity = await gateway._client.get_entity(username)
        snapshot = _try_public_chat_snapshot(entity)
        if snapshot is None:
            return
        source = add_snapshot(ledger, snapshot, provenance, hit)
        if snapshot.source_type != "megagroup" or not snapshot.username:
            source["rejection"] = "not_public_megagroup"
    except Exception as exc:  # noqa: BLE001
        ledger["resolution_errors"].append(
            {"username": username, "provenance": provenance, "error": type(exc).__name__}
        )


async def discover_global(
    gateway: TelethonTelegramGateway,
    ledger: dict[str, Any],
    now: datetime,
    queries: tuple[str, ...] = QUERIES,
) -> None:
    after = now - timedelta(days=30)
    for query_index, query in enumerate(queries, 1):
        if query in ledger["completed_queries"]:
            print(f"GLOBAL {query_index}/{len(queries)} cached", flush=True)
            continue
        offset_rate = 0
        offset_peer: Any = InputPeerEmpty()
        offset_id = 0
        cursors: set[tuple[int, int, int]] = set()
        page_count = 0
        while True:
            result = await gateway._invoke(
                SearchGlobalRequest(
                    q=query,
                    filter=InputMessagesFilterEmpty(),
                    min_date=after,
                    max_date=now,
                    offset_rate=offset_rate,
                    offset_peer=offset_peer,
                    offset_id=offset_id,
                    limit=PAGE_SIZE,
                    broadcasts_only=None,
                    groups_only=True,
                    users_only=None,
                    folder_id=None,
                )
            )
            messages = list(getattr(result, "messages", None) or ())
            chats = {
                int(chat.id): chat
                for chat in (getattr(result, "chats", None) or ())
                if getattr(chat, "id", None) is not None
            }
            if not messages:
                break
            page_count += 1
            for message in messages:
                chat = chats.get(peer_id(message) or 0)
                snapshot = _try_public_chat_snapshot(chat) if chat is not None else None
                if snapshot is None:
                    continue
                published = message.date
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                link = (
                    f"https://t.me/{snapshot.username}/{int(message.id)}"
                    if snapshot.username
                    else None
                )
                text = str(getattr(message, "message", "") or "").strip()
                if not likely_order(text):
                    continue
                source = add_snapshot(
                    ledger,
                    snapshot,
                    "telegram_global_message",
                    {
                        "query": query,
                        "published_at": published.isoformat(),
                        "permalink": link,
                        "text": text[:2000],
                    },
                )
                if snapshot.source_type != "megagroup" or not snapshot.username:
                    source["rejection"] = "not_public_megagroup"
            last = messages[-1]
            last_id = int(getattr(last, "id", 0) or 0)
            last_peer_id = peer_id(last) or 0
            last_chat = chats.get(last_peer_id)
            last_date = getattr(last, "date", after)
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=UTC)
            next_rate_raw = getattr(result, "next_rate", None)
            next_rate = int(next_rate_raw if next_rate_raw is not None else last_date.timestamp())
            cursor = (next_rate, last_peer_id, last_id)
            if (
                last_id <= 0
                or last_chat is None
                or cursor in cursors
                or last_date < after
                or page_count >= MAX_GLOBAL_PAGES_PER_QUERY
            ):
                break
            cursors.add(cursor)
            offset_rate = next_rate
            offset_peer = utils.get_input_peer(last_chat)
            offset_id = last_id
            if next_rate_raw is None and len(messages) < PAGE_SIZE:
                break
            await asyncio.sleep(0.7)
        ledger["completed_queries"].append(query)
        save_ledger(ledger)
        print(f"GLOBAL {query_index}/{len(queries)} sources={len(ledger['sources'])}", flush=True)
        await asyncio.sleep(0.8)


async def discover_aggregator_origins(
    gateway: TelethonTelegramGateway, ledger: dict[str, Any], now: datetime
) -> None:
    after = now - timedelta(days=30)
    client = gateway._client
    for username in AGGREGATORS:
        try:
            entity = await client.get_entity(username)
            async for message in client.iter_messages(entity, limit=None):
                published = message.date
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                if published < after:
                    break
                text = str(message.message or "")
                if not likely_order(text):
                    continue
                forward = getattr(message, "fwd_from", None)
                origin_peer = None
                origin_message_id = None
                if forward is not None:
                    origin_peer = getattr(forward, "saved_from_peer", None) or getattr(
                        forward, "from_id", None
                    )
                    origin_message_id = getattr(forward, "saved_from_msg_id", None) or getattr(
                        forward, "channel_post", None
                    )
                if origin_peer is not None and origin_message_id:
                    try:
                        origin = await client.get_entity(origin_peer)
                        snapshot = _try_public_chat_snapshot(origin)
                        if snapshot is not None and snapshot.username:
                            source = add_snapshot(
                                ledger,
                                snapshot,
                                f"aggregator_origin:@{username}",
                                {
                                    "query": "aggregator_original",
                                    "published_at": published.isoformat(),
                                    "permalink": f"https://t.me/{snapshot.username}/{int(origin_message_id)}",
                                    "text": text[:2000],
                                },
                            )
                            if snapshot.source_type != "megagroup":
                                source["rejection"] = "not_public_megagroup"
                    except Exception:  # noqa: BLE001
                        pass
                for linked_username, linked_message_id in TME_LINK_RE.findall(text):
                    await resolve_and_add(
                        gateway,
                        ledger,
                        linked_username,
                        f"aggregator_link:@{username}",
                        {
                            "query": "aggregator_original_link",
                            "published_at": published.isoformat(),
                            "permalink": f"https://t.me/{linked_username}/{linked_message_id}",
                            "text": text[:2000],
                        },
                    )
            print(f"AGGREGATOR @{username} sources={len(ledger['sources'])}", flush=True)
        except Exception as exc:  # noqa: BLE001
            ledger["resolution_errors"].append(
                {"username": username, "provenance": "aggregator", "error": type(exc).__name__}
            )
        save_ledger(ledger)
        await asyncio.sleep(0.8)


async def discover_global_aggregator_origins(
    gateway: TelethonTelegramGateway,
    ledger: dict[str, Any],
    now: datetime,
    queries: tuple[str, ...] = CONTINUATION_QUERIES_9,
) -> None:
    """Find order reposts globally, but retain only their original group post."""
    after = now - timedelta(days=30)
    client = gateway._client
    for query_index, query in enumerate(queries, 1):
        offset_rate = 0
        offset_peer: Any = InputPeerEmpty()
        offset_id = 0
        cursors: set[tuple[int, int, int]] = set()
        page_count = 0
        while True:
            result = await gateway._invoke(
                SearchGlobalRequest(
                    q=query,
                    filter=InputMessagesFilterEmpty(),
                    min_date=after,
                    max_date=now,
                    offset_rate=offset_rate,
                    offset_peer=offset_peer,
                    offset_id=offset_id,
                    limit=PAGE_SIZE,
                    broadcasts_only=True,
                    groups_only=None,
                    users_only=None,
                    folder_id=None,
                )
            )
            messages = list(getattr(result, "messages", None) or ())
            chats = {
                int(chat.id): chat
                for chat in (getattr(result, "chats", None) or ())
                if getattr(chat, "id", None) is not None
            }
            if not messages:
                break
            page_count += 1
            for message in messages:
                text = str(getattr(message, "message", "") or "").strip()
                if not likely_order(text):
                    continue
                forward = getattr(message, "fwd_from", None)
                origin_peer = getattr(forward, "saved_from_peer", None) if forward else None
                origin_message_id = (
                    getattr(forward, "saved_from_msg_id", None) if forward else None
                )
                if origin_peer is not None and origin_message_id:
                    try:
                        origin = await client.get_entity(origin_peer)
                        snapshot = _try_public_chat_snapshot(origin)
                        if snapshot is not None and snapshot.username:
                            source = add_snapshot(
                                ledger,
                                snapshot,
                                "telegram_global_aggregator_origin",
                                {
                                    "query": query,
                                    "permalink": f"https://t.me/{snapshot.username}/{int(origin_message_id)}",
                                    "text": text[:2000],
                                },
                            )
                            if snapshot.source_type != "megagroup":
                                source["rejection"] = "not_public_megagroup"
                    except Exception:  # noqa: BLE001
                        pass
                for linked_username, linked_message_id in TME_LINK_RE.findall(text):
                    await resolve_and_add(
                        gateway,
                        ledger,
                        linked_username,
                        "telegram_global_aggregator_link",
                        {
                            "query": query,
                            "permalink": f"https://t.me/{linked_username}/{linked_message_id}",
                            "text": text[:2000],
                        },
                    )
            last = messages[-1]
            last_id = int(getattr(last, "id", 0) or 0)
            last_peer_id = peer_id(last) or 0
            last_chat = chats.get(last_peer_id)
            last_date = getattr(last, "date", after)
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=UTC)
            next_rate_raw = getattr(result, "next_rate", None)
            next_rate = int(next_rate_raw if next_rate_raw is not None else last_date.timestamp())
            cursor = (next_rate, last_peer_id, last_id)
            if (
                last_id <= 0
                or last_chat is None
                or cursor in cursors
                or last_date < after
                or page_count >= MAX_GLOBAL_PAGES_PER_QUERY
            ):
                break
            cursors.add(cursor)
            offset_rate = next_rate
            offset_peer = utils.get_input_peer(last_chat)
            offset_id = last_id
            await asyncio.sleep(0.7)
        save_ledger(ledger)
        print(
            f"GLOBAL_AGGREGATOR {query_index}/{len(queries)} "
            f"sources={len(ledger['sources'])}",
            flush=True,
        )
        await asyncio.sleep(0.8)


async def scan_order_candidates(
    gateway: TelethonTelegramGateway, ledger: dict[str, Any], now: datetime
) -> None:
    after = now - timedelta(days=30)
    client = gateway._client
    candidates = [
        source
        for source in ledger["sources"].values()
        if source["source_type"] == "megagroup" and source["username"]
    ]
    for index, source in enumerate(candidates, 1):
        if source.get("order_scan_complete"):
            print(
                f"ORDERS {index}/{len(candidates)} @{source['username']} cached",
                flush=True,
            )
            continue
        seen_hashes: set[str] = set()
        rows: list[dict[str, Any]] = []
        completed_searches = 0
        try:
            entity = await client.get_entity(source["username"])
            for object_query in OBJECTS:
                async for message in client.iter_messages(
                    entity, limit=None, search=object_query
                ):
                    published = message.date
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=UTC)
                    if published < after:
                        break
                    text = str(message.message or "").strip()
                    if (
                        not text
                        or not likely_order(text)
                        or getattr(message, "fwd_from", None)
                    ):
                        continue
                    author_kind, author_id = classify_message_author(message)
                    sender = getattr(message, "sender", None)
                    if (
                        author_kind != "user"
                        or author_id is None
                        or bool(getattr(sender, "bot", False))
                        or bool(getattr(sender, "deleted", False))
                    ):
                        continue
                    digest = hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    rows.append(
                        {
                            "message_id": int(message.id),
                            "published_at": published.isoformat(),
                            "author_id": int(author_id),
                            "permalink": f"https://t.me/{source['username']}/{int(message.id)}",
                            "normalized_hash": digest,
                            "text": text,
                        }
                    )
                completed_searches += 1
                await asyncio.sleep(0.25)
            source["order_candidates"] = rows
            source["order_scan_complete"] = completed_searches == len(OBJECTS)
            source["order_candidate_authors"] = len({row["author_id"] for row in rows})
            source["rejection"] = None
        except Exception as exc:  # noqa: BLE001
            source["order_scan_complete"] = False
            source["rejection"] = f"history_error:{type(exc).__name__}"
        save_ledger(ledger)
        print(
            f"ORDERS {index}/{len(candidates)} @{source['username']} "
            f"messages={len(source['order_candidates'])} "
            f"authors={source.get('order_candidate_authors', 0)}",
            flush=True,
        )
        await asyncio.sleep(0.5)


async def discover() -> int:
    now = datetime.now(UTC)
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "run_at": now.isoformat(),
        "method": "reverse_message_to_public_megagroup",
        "queries": list(QUERIES),
        "completed_queries": [],
        "sources": {},
        "resolution_errors": [],
    }
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now)
        for provenance, username in load_external():
            await resolve_and_add(gateway, ledger, username, provenance)
            await asyncio.sleep(0.3)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def orders_only() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES)
        for provenance, username in load_external():
            await resolve_and_add(gateway, ledger, username, provenance)
            await asyncio.sleep(0.3)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_2() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_2"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_2:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_2)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_3() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_3"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_3:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_3)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_4() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_4"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_4:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_4)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_5() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_5"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_5:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_5)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_6() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_6"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_6:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_6)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_7() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_7"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_7:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_7)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_8() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_8"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_8:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_8)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_9() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_9"] = now.isoformat()
    known_queries = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_9:
        if query not in known_queries:
            known_queries.append(query)
    ledger["queries"] = known_queries
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_9)
        save_ledger(ledger)
        await discover_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_10() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_10"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(gateway, ledger, now)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_11() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_11"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(
            gateway, ledger, now, CONTINUATION_QUERIES
        )
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_12() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_12"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(
            gateway, ledger, now, CONTINUATION_QUERIES_2
        )
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_13() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_13"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(
            gateway, ledger, now, CONTINUATION_QUERIES_3
        )
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_14() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_14"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(
            gateway, ledger, now, CONTINUATION_QUERIES_4
        )
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_15() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["continued_at_15"] = now.isoformat()
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global_aggregator_origins(
            gateway, ledger, now, CONTINUATION_QUERIES_5
        )
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_parser_candidates() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["prior_candidate_import_at"] = now.isoformat()
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_parser_candidates():
            await resolve_and_add(gateway, ledger, username, "prior_parser_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_parser_candidates_2() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["prior_candidate_import_2_at"] = now.isoformat()
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_parser_candidates(offset=80):
            await resolve_and_add(gateway, ledger, username, "prior_parser_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_parser_candidates_3() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_parser_candidates(offset=160):
            await resolve_and_add(gateway, ledger, username, "prior_parser_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_parser_candidates_4() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_parser_candidates(offset=240):
            await resolve_and_add(gateway, ledger, username, "prior_parser_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_parser_candidates_5() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_parser_candidates(offset=320):
            await resolve_and_add(gateway, ledger, username, "prior_parser_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def import_prior_report_candidates() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        for username in load_prior_report_candidates():
            await resolve_and_add(gateway, ledger, username, "prior_parser_report_candidate")
            await asyncio.sleep(0.25)
        save_ledger(ledger)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_16() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    known = list(ledger.get("queries", []))
    for query in CONTINUATION_QUERIES_16:
        if query not in known:
            known.append(query)
    ledger["queries"] = known
    save_ledger(ledger)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_16)
        await discover_global_aggregator_origins(gateway, ledger, now, CONTINUATION_QUERIES_16)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_17() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized(): raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_17)
        await discover_global_aggregator_origins(gateway, ledger, now, CONTINUATION_QUERIES_17)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_18() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized(): raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_18)
        await discover_global_aggregator_origins(gateway, ledger, now, CONTINUATION_QUERIES_18)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def continue_search_19() -> int:
    now = datetime.now(UTC)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized(): raise RuntimeError("telegram_session_not_authorized")
        await discover_global(gateway, ledger, now, CONTINUATION_QUERIES_19)
        await scan_order_candidates(gateway, ledger, now)
        return 0
    finally:
        await gateway.disconnect()


async def activity() -> int:
    now = datetime.now(UTC)
    after = now - timedelta(days=14)
    evidence = json.loads(MANUAL.read_text(encoding="utf-8"))
    accepted = evidence.get("accepted", [])
    final_usernames: list[str] = []
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        account = await gateway.connect()
        if not account.connected or not await gateway._client.is_user_authorized():
            raise RuntimeError("telegram_session_not_authorized")
        client = gateway._client
        for item in accepted:
            username = str(item["username"]).lstrip("@")
            if item.get("activity", {}).get("passed") is True:
                final_usernames.append(f"@{username}")
                print(f"ACTIVITY @{username} cached passed=True", flush=True)
                continue
            entity = await client.get_entity(username)
            snapshot = _try_public_chat_snapshot(entity)
            if snapshot is None or snapshot.source_type != "megagroup" or not snapshot.username:
                item["activity"] = {"passed": False, "reason": "not_public_megagroup"}
                continue
            message_count = 0
            active_days: set[str] = set()
            authors: set[int] = set()
            reached_boundary = False
            async for message in client.iter_messages(entity, limit=None):
                published = message.date
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                if published < after:
                    reached_boundary = True
                    break
                text = str(message.message or "").strip()
                if not text:
                    continue
                message_count += 1
                active_days.add(published.date().isoformat())
                author_kind, author_id = classify_message_author(message)
                sender = getattr(message, "sender", None)
                if (
                    author_kind == "user"
                    and author_id is not None
                    and not bool(getattr(sender, "bot", False))
                    and not bool(getattr(sender, "deleted", False))
                ):
                    authors.add(int(author_id))
            history_complete = True
            passed = bool(
                history_complete
                and message_count >= 100
                and len(active_days) >= 10
                and len(authors) >= 20
            )
            item["activity"] = {
                "passed": passed,
                "history_complete": history_complete,
                "messages": message_count,
                "days": len(active_days),
                "authors": len(authors),
            }
            if passed:
                final_usernames.append(f"@{snapshot.username}")
            MANUAL.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"ACTIVITY @{username} messages={message_count} days={len(active_days)} "
                f"authors={len(authors)} passed={passed}",
                flush=True,
            )
        RESULT.write_text(
            "" if not final_usernames else "\n".join(final_usernames) + "\n",
            encoding="utf-8",
        )
        return 0
    finally:
        await gateway.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("discover", "continue", "continue2", "continue3", "continue4", "continue5", "continue6", "continue7", "continue8", "continue9", "continue10", "continue11", "continue12", "continue13", "continue14", "continue15", "continue16", "continue17", "continue18", "continue19", "prior-import", "prior-import-2", "prior-import-3", "prior-import-4", "prior-import-5", "prior-report", "orders", "activity"))
    args = parser.parse_args()
    if args.phase == "discover":
        operation = discover()
    elif args.phase == "continue":
        operation = continue_search()
    elif args.phase == "continue2":
        operation = continue_search_2()
    elif args.phase == "continue3":
        operation = continue_search_3()
    elif args.phase == "continue4":
        operation = continue_search_4()
    elif args.phase == "continue5":
        operation = continue_search_5()
    elif args.phase == "continue6":
        operation = continue_search_6()
    elif args.phase == "continue7":
        operation = continue_search_7()
    elif args.phase == "continue8":
        operation = continue_search_8()
    elif args.phase == "continue9":
        operation = continue_search_9()
    elif args.phase == "continue10":
        operation = continue_search_10()
    elif args.phase == "continue11":
        operation = continue_search_11()
    elif args.phase == "continue12":
        operation = continue_search_12()
    elif args.phase == "continue13":
        operation = continue_search_13()
    elif args.phase == "continue14":
        operation = continue_search_14()
    elif args.phase == "continue15":
        operation = continue_search_15()
    elif args.phase == "prior-import":
        operation = import_prior_parser_candidates()
    elif args.phase == "prior-import-2":
        operation = import_prior_parser_candidates_2()
    elif args.phase == "prior-import-3":
        operation = import_prior_parser_candidates_3()
    elif args.phase == "prior-import-4":
        operation = import_prior_parser_candidates_4()
    elif args.phase == "prior-import-5":
        operation = import_prior_parser_candidates_5()
    elif args.phase == "prior-report":
        operation = import_prior_report_candidates()
    elif args.phase == "continue16":
        operation = continue_search_16()
    elif args.phase == "continue17":
        operation = continue_search_17()
    elif args.phase == "continue18":
        operation = continue_search_18()
    elif args.phase == "continue19":
        operation = continue_search_19()
    elif args.phase == "orders":
        operation = orders_only()
    else:
        operation = activity()
    return asyncio.run(operation)


if __name__ == "__main__":
    raise SystemExit(main())

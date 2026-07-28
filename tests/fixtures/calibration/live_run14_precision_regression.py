"""Run14 DET precision regression excerpts (honest sanitized derivatives).

Provenance: ``operator_run_14_sanitized_excerpt`` — NOT owner-labeled population data.
C01–C20 / T1–T5 provenance is unchanged (see ``live_run13_c01_c20.py``).

Evidence ids are stable from operator keyword ``run_id=14`` (read-only extract).
Names / @usernames / contacts masked as ``[скрыто]``.
"""

from __future__ import annotations

import re

PROVENANCE_RUN14 = "operator_run_14_sanitized_excerpt"

# Stable evidence-id map (operator run 14 qualified rows used for regression).
EVIDENCE_ID_BY_SAMPLE: dict[str, int] = {
    "R14-FP01": 67,
    "R14-FP02": 73,
    "R14-FP03": 74,
    "R14-FP04": 75,
    "R14-FP05": 77,
    "R14-KEEP01": 86,
    "R14-FP06": 89,
    "R14-FP07": 90,
    "R14-FP08": 91,
    "R14-FP09": 92,
    "R14-FP10": 99,
    "R14-FP11": 100,
    "R14-FP12": 118,
    "R14-FP13": 120,
}


def sanitize_excerpt(text: str) -> str:
    out = text
    out = re.sub(r"(?i)(меня\s+зовут\s+)\S+", r"\1[скрыто]", out)
    out = re.sub(r"(?<!\w)@([A-Za-z][\w_]{2,})", "@[скрыто]", out)
    out = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[скрыто]", out)
    out = re.sub(r"\+?\d[\d\-\s()]{8,}\d", "[скрыто]", out)
    # First names appearing as specialist card headers.
    out = re.sub(r"(?i)\b(?:Ольга|Дарья|Екатерина|Максим)\b", "[скрыто]", out)
    return out


_RAW: dict[str, tuple[str, bool]] = {
    "R14-FP01": (
        "Привет! Разрабатываю Telegram-ботов, автоматизацию (VK, сайты) и AI-агентов — "
        "с оплатой, базами данных, интеграциями. Есть готовые кейсы: бот с приёмом оплаты",
        False,
    ),
    "R14-FP02": (
        "Вполне возможно, что маркетплейс таким образом перераспределяет поток заказов "
        "между моделями работы. FBS снижает нагрузку на склады",
        False,
    ),
    "R14-FP03": (
        "Wildberries платит селлерам после атак на склады. Но оферта говорит иное — и это важно",
        False,
    ),
    "R14-FP04": (
        "Как подключить перераспределение остатков? Я никак не могу найти его, "
        "как будто бы Wildberries скрыл",
        False,
    ),
    "R14-FP05": (
        "Кому нужен бухгалтер под маркетплейсы — вот хороший канал специалиста",
        False,
    ),
    "R14-KEEP01": (
        "Девочки, привет! Кто как автоматизирует работу с Wildberries? Или все ручками делают?",
        True,
    ),
    "R14-FP06": (
        "Добрый день! Я занимаюсь оформлением карточек Wildberries: обложки, инфографика, SEO. "
        "Могу показать вариант",
        False,
    ),
    "R14-FP07": (
        "Добрый день, нужны кому-то услуги разработчика? Пишу парсеры, сайты, боты и много чего еще",
        False,
    ),
    "R14-FP08": ("А мне нужно отгрузить текущие заказы. И что теперь", False),
    "R14-FP09": (
        "Удаленка в Ozon Support! Без опыта. Ищем специалистов поддержки пользователей и партнеров Ozon",
        False,
    ),
    "R14-FP10": (
        "Ольга | Менеджер маркетплейсов + дизайнер инфографики. Что умею: Поставки под ключ",
        False,
    ),
    "R14-FP11": (
        "Здравствуйте! Меня зовут Дарья, откликаюсь на вакансию помощника менеджера маркетплейсов",
        False,
    ),
    "R14-FP12": (
        "Екатерина | Менеджер маркетплейсов Ozon • WB. Помогаю брендам увеличивать продажи. "
        "Опыт работы с 2022 года",
        False,
    ),
    "R14-FP13": ("#специалист (менеджер). Проведу бесплатный аудит", False),
}

SAMPLES: list[tuple[str, str, bool, str, int]] = [
    (
        sid,
        sanitize_excerpt(raw),
        is_client,
        PROVENANCE_RUN14,
        EVIDENCE_ID_BY_SAMPLE[sid],
    )
    for sid, (raw, is_client) in _RAW.items()
]


def iter_run14_regression_samples() -> list[tuple[str, str, bool, str]]:
    return [(sid, text, is_client, prov) for sid, text, is_client, prov, _ in SAMPLES]

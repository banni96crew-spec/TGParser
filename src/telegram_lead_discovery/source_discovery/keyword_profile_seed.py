"""Immutable seed keyword profile data."""

from typing import Literal

SourceScope = Literal["groups", "channels", "all"]

MIN_QUERY_LEN = 3
MAX_QUERY_LEN = 128
MAX_POST_QUERIES = 20
MIN_POST_QUERIES = 1
MAX_DIRECTORY_QUERIES = 10
MIN_DIRECTORY_QUERIES = 0
MAX_PROFILE_NAME_LEN = 80
MAX_EVIDENCE_EXCERPT_CODEPOINTS = 240

SEED_PROFILE_NAME = "ecommerce-development-ru"
SEED_PROFILE_VERSION = 2

SEED_POST_QUERIES: tuple[str, ...] = (
    # websites
    "нужен сайт",
    "ищу разработчика сайта",
    "кто сделает сайт",
    "нужен лендинг",
    # telegram_bots
    "нужен telegram бот",
    "разработать telegram бота",
    "нужен бот для заказов",
    # integrations_api
    "нужна интеграция api",
    "интеграция сайта crm",
    "интеграция с 1с",
    # automation_parsers
    "нужен парсер",
    "автоматизировать заказы",
    "нужна автоматизация",
    # ecommerce
    "нужен интернет-магазин",
    "доработать интернет-магазин",
    "интеграция ozon",
    "интеграция wildberries",
    "нужен магазин на сайте",
)

# Primary directory lane (SRC-018 cap 0..10): client/operator communities across
# five service families — not marketplace-seller-only (D-069).
SEED_DIRECTORY_QUERIES: tuple[str, ...] = (
    "чат предпринимателей",
    "сообщество предпринимателей",
    "владельцы бизнеса",
    "заказчики сайтов",
    "чат владельцев ботов",
    "интеграции api сообщество",
    "автоматизация бизнеса чат",
    "владельцы интернет-магазинов",
    "основатели стартапов",
    "сообщество заказчиков",
)

# Free replacement directory family after mass suppress (SRC-040 / D-069).
# Not counted against SRC-018 profile directory cap; worker expansion only.
SEED_DIRECTORY_REPLACEMENT_QUERIES: tuple[str, ...] = (
    "ищу разработчика чат",
    "нужен сайт сообщество",
    "лендинг для бизнеса",
    "telegram боты для бизнеса",
    "чат заказчиков ботов",
    "crm интеграция сообщество",
    "1с интеграция чат",
    "парсеры и автоматизация",
    "чат автоматизации процессов",
    "ecommerce владельцы чат",
    "интернет магазин сообщество",
    "чат предпринимателей рф",
    "малый бизнес сообщество",
    "заказчики it услуг",
    "клиенты на разработку",
)

SEED_ADDITIONAL_EXCLUSIONS: tuple[str, ...] = (
    "ищем в команду",
    "резюме",
    "ищу работу",
    "предлагаю услуги",
    "курс",
    "обучение",
)

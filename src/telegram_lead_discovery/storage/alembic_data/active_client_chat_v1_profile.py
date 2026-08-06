"""Frozen operator seed written by migration 006."""

from sqlalchemy import text

POST_QUERIES = (
    "нужен сайт",
    "ищу разработчика сайта",
    "кто сделает сайт",
    "нужен лендинг",
    "нужен telegram бот",
    "разработать telegram бота",
    "нужен бот для заказов",
    "нужна интеграция api",
    "интеграция сайта crm",
    "интеграция с 1с",
    "нужен парсер",
    "автоматизировать заказы",
    "нужна автоматизация",
    "нужен интернет-магазин",
    "доработать интернет-магазин",
    "интеграция ozon",
    "интеграция wildberries",
    "нужен магазин на сайте",
)

DIRECTORY_QUERIES = (
    "чат предпринимателей",
    "сообщество предпринимателей",
    "владельцы бизнеса",
    "основатели стартапов",
    "владельцы интернет-магазинов",
    "чат селлеров",
    "рестораторы чат",
    "владельцы салонов чат",
    "онлайн-школы чат",
    "малый бизнес чат",
)

REPLACEMENT_DIRECTORY_QUERIES = (
    "предприниматели москва",
    "предприниматели спб",
    "предприниматели казань",
    "предприниматели екатеринбург",
    "предприниматели краснодар",
    "малый бизнес сообщество",
    "владельцы кафе чат",
    "владельцы ресторанов чат",
    "владельцы салонов красоты чат",
    "онлайн школы сообщество",
    "частные клиники чат",
    "турбизнес чат",
    "риелторы предприниматели чат",
    "производители чат",
    "локальный бизнес чат",
)

ADDITIONAL_EXCLUSIONS = (
    "ищем в команду",
    "резюме",
    "ищу работу",
    "предлагаю услуги",
    "курс",
    "обучение",
)


def downgrade_seed_profile(bind, tables: set[str]) -> None:
    required = {"keyword_discovery_profiles", "keyword_discovery_profile_versions"}
    if not required <= tables:
        return
    profile = bind.execute(
        text("SELECT id, current_version FROM keyword_discovery_profiles WHERE name=:name"),
        {"name": "ecommerce-development-ru"},
    ).fetchone()
    if profile is None:
        return
    profile_id, current_version = int(profile[0]), int(profile[1])
    if current_version == 6:
        return
    if current_version != 7:
        raise RuntimeError(f"seed_profile_downgrade_requires_version_7:found={current_version}")
    bind.execute(
        text(
            "UPDATE keyword_discovery_profiles SET current_version=6, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:pid"
        ),
        {"pid": profile_id},
    )
    bind.execute(
        text("DELETE FROM keyword_discovery_profile_versions WHERE profile_id=:pid AND version=7"),
        {"pid": profile_id},
    )

"""DET-A seed catalog for RuleSetVersion ru-mvp-1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import MonitoringRule, RuleSetVersion

RULE_FLAGS = "IGNORECASE|FULLCASE|VERSION1"


@dataclass(frozen=True, slots=True)
class SeedRule:
    stable_rule_id: str
    priority: int
    target: str
    dimension: str
    weight: int
    pattern: str
    explanation_code: str
    kind: str


def _kind_for(dimension: str) -> str:
    if dimension == "hard_exclusion":
        return "hard_exclusion"
    if dimension == "service_fit":
        return "service"
    if dimension == "intent":
        return "positive_intent"
    return "signal"


def _r(
    rule_id: str,
    priority: int,
    target: str,
    dimension: str,
    weight: int,
    pattern: str,
    explanation_code: str,
) -> SeedRule:
    return SeedRule(
        stable_rule_id=rule_id,
        priority=priority,
        target=target,
        dimension=dimension,
        weight=weight,
        pattern=pattern,
        explanation_code=explanation_code,
        kind=_kind_for(dimension),
    )


# Exact DET-A catalog from docs/prd/modules/04-lead-detection/PRD.md
SEED_RULES: tuple[SeedRule, ...] = (
    # Hard exclusions
    _r("NEG-SPAM-001", 100, "spam", "hard_exclusion", 0, r"\b(?:казино|слоты|ставки на спорт|букмекер|джекпот)\b", "spam_gambling"),
    _r("NEG-SPAM-002", 101, "spam", "hard_exclusion", 0, r"\b(?:гарантированный заработок|быстрый заработок|доход без вложений|крипто[- ]?сигналы|раздача криптовалюты)\b", "spam_income"),
    _r("NEG-SPAM-003", 102, "spam", "hard_exclusion", 0, r"\b(?:рассылка по чатам|массовая рассылка|накрутка подписчиков|накрутка реакций)\b", "spam_bulk"),
    _r("NEG-ADV-001", 120, "advertising", "hard_exclusion", 0, r"\b(?:мы|наша команда|наше агентство)\b.{0,80}\b(?:делаем|разрабатываем|создаём|оказываем|предлагаем)\b", "advertising_provider"),
    _r("NEG-ADV-002", 121, "advertising", "hard_exclusion", 0, r"\b(?:скидка|акция|спецпредложение|специальное предложение)\b.{0,80}\b(?:на сайт|на разработку|на бота|на услуги|до пятницы|до конца месяца)\b", "advertising_promo"),
    _r("NEG-ADV-003", 122, "advertising", "hard_exclusion", 0, r"\b(?:принимаем заказы|свободны для новых проектов|возьмём ваш проект|закажите у нас)\b", "advertising_solicitation"),
    _r("NEG-VAC-001", 140, "vacancy", "hard_exclusion", 0, r"\b(?:вакансия|открыта позиция|открыта вакансия|ищем сотрудника)\b", "vacancy_marker"),
    _r("NEG-VAC-002", 141, "vacancy", "hard_exclusion", 0, r"\b(?:в штат|полная занятость|частичная занятость|оформление по тк|трудоустройство)\b", "vacancy_employment"),
    _r("NEG-VAC-003", 142, "vacancy", "hard_exclusion", 0, r"\b(?:зарплата|оклад)\b\s*(?:от\s*)?\d[\d\s]{2,}", "vacancy_salary"),
    _r("NEG-VAC-004", 143, "vacancy", "hard_exclusion", 0, r"(?:https?://)?(?:www\.)?(?:hh\.ru|career\.habr\.com)/\S+", "vacancy_link"),
    _r("NEG-VAC-005", 144, "vacancy", "hard_exclusion", 0, r"\b(?:присылайте резюме|отправляйте резюме|откликнуться на вакансию|испытательный срок)\b", "vacancy_application"),
    # Services
    _r("SVC-WEB-001", 200, "websites", "service_fit", 12, r"\b(?:сайт(?:а|е|ом|у|ы|ов)?|лендинг(?:а|е|и|ов)?|веб[- ]?приложени(?:е|я|ю|ем|й)|frontend|backend|фронтенд|бэкенд)\b", "service_websites"),
    _r("SVC-WEB-002", 201, "websites", "service_fit", 8, r"\b(?:wordpress|tilda|webflow|react|vue|django|fastapi)\b", "service_web_stack"),
    _r("SVC-BOT-001", 210, "telegram_bots", "service_fit", 12, r"\b(?:telegram|телеграм|тг)\b.{0,30}\b(?:бот(?:а|е|ом|у|ы|ов)?|mini app|мини[- ]?приложени(?:е|я))\b", "service_telegram_bot"),
    _r("SVC-BOT-002", 211, "telegram_bots", "service_fit", 8, r"\b(?:чат[- ]?бот(?:а|ы|ов)?|бот для (?:заказов|оплаты|поддержки|записи))\b", "service_chatbot"),
    _r("SVC-INT-001", 220, "integrations_api", "service_fit", 12, r"\b(?:интеграц(?:ия|ии|ию|ией)|api|апи|webhook|вебхук)\b", "service_integration"),
    _r("SVC-INT-002", 221, "integrations_api", "service_fit", 8, r"\b(?:crm|amo ?crm|битрикс ?24|1с|мой ?склад)\b", "service_business_system"),
    _r("SVC-AUT-001", 230, "automation_parsers", "service_fit", 12, r"\b(?:автоматизац(?:ия|ии|ию|ией)|автоматизировать|автоматизируем|автоматизируется|парсер(?:а|ы|ов)?|парсинг|скрейпинг|scraping)\b", "service_automation"),
    _r("SVC-AUT-002", 231, "automation_parsers", "service_fit", 8, r"\b(?:сбор данных|выгрузка данных|обработка данных|перенос данных)\b", "service_data_flow"),
    _r("SVC-ECOM-001", 240, "ecommerce", "service_fit", 12, r"\b(?:интернет[- ]?магазин(?:а|е|ы|ов)?|e[- ]?commerce|электронн(?:ая|ой) коммерци(?:я|и))\b", "service_ecommerce"),
    _r("SVC-ECOM-002", 241, "ecommerce", "service_fit", 8, r"\b(?:маркетплейс(?:а|е|ы|ов)?|wildberries|ozon|яндекс маркет|товарн(?:ый|ого) каталог|корзин(?:а|ы)|перенос заказов|обработка заказов|приём заказов)\b", "service_marketplace"),
    # Positive intent
    _r("POS-DIR-001", 300, "direct_order", "intent", 15, r"\b(?:нужно|надо|хочу|хотим|планирую|планируем)\b.{0,100}\b(?:сделать|разработать|создать|доработать|исправить|настроить|подключить|интегрировать|автоматизировать|перенести|запустить)\b", "intent_direct_need"),
    _r("POS-DIR-002", 301, "direct_order", "intent", 15, r"\b(?:задача|тз|техническое задание)\b.{0,100}\b(?:сделать|разработать|создать|доработать|исправить|настроить|подключить|интегрировать|автоматизировать)\b", "intent_direct_task"),
    _r("POS-DIR-003", 302, "direct_order", "intent", 12, r"\b(?:кто|кто-нибудь|кто-то)\b.{0,60}\b(?:сделает|разработает|создаст|доработает|настроит|подключит|интегрирует|автоматизирует)\b", "intent_direct_who"),
    _r("POS-DIR-004", 303, "direct_order", "intent", 18, r"\b(?:заказать|закажу|готов оплатить|готовы оплатить)\b.{0,80}\b(?:сайт|лендинг|бот|интеграцию|автоматизацию|парсер|интернет[- ]?магазин)\b", "intent_direct_purchase"),
    _r("POS-CTR-001", 320, "contractor_search", "intent", 14, r"\b(?:ищу|ищем|нужен|нужна|нужны|требуется|требуются)\b.{0,80}\b(?:разработчик(?:а|и|ов)?|программист(?:а|ы|ов)?|фрилансер(?:а|ы|ов)?|специалист(?:а|ы|ов)?|подрядчик(?:а|и|ов)?|исполнитель|команда|агентство)\b", "intent_contractor_search"),
    _r("POS-CTR-002", 321, "contractor_search", "intent", 10, r"\b(?:кто возьмётся|кто может взяться|есть свободный разработчик|есть свободный специалист)\b", "intent_contractor_available"),
    _r("POS-REC-001", 340, "recommendation_request", "intent", 10, r"\b(?:посоветуйте|порекомендуйте|можете посоветовать|можете порекомендовать)\b.{0,100}\b(?:разработчик(?:а)?|программист(?:а)?|специалист(?:а)?|подрядчик(?:а)?|исполнитель|команду|агентство)\b", "intent_recommend_person"),
    _r("POS-REC-002", 341, "recommendation_request", "intent", 8, r"\b(?:у кого есть контакты|дайте контакт|поделитесь контактом|кого можете рекомендовать)\b", "intent_recommend_contact"),
    _r("POS-POT-001", 360, "potential_need", "intent", 6, r"\b(?:можно ли|реально ли|как лучше|как можно|как)\b.{0,100}\b(?:сделать|реализовать|подключить|интегрировать|автоматизировать|перенести|собрать)\b", "intent_potential_how"),
    _r("POS-POT-002", 361, "potential_need", "intent", 5, r"\b(?:есть|возникла|появилась|столкнулся|столкнулись)\b.{0,40}\b(?:проблема|ошибка|сложность|потребность)\b", "intent_potential_problem"),
    _r("POS-POT-003", 362, "potential_need", "intent", 5, r"\b(?:устал|устали)\b.{0,60}\b(?:вручную|руками|копировать|переносить|обрабатывать)\b", "intent_potential_manual_work"),
    # Signals
    _r("SIG-BUD-001", 400, "budget_present", "budget", 10, r"\b(?:бюджет|стоимость|оплата)\b\s*(?:[:=—-]\s*)?(?:до\s*|от\s*)?\d[\d\s]*(?:₽|руб(?:лей|ля|\.)?|р\b|usd|eur|\$|€)", "signal_budget_amount"),
    _r("SIG-BUD-002", 401, "budget_present", "budget", 8, r"\b(?:готов|готовы|готова)\s+(?:заплатить|оплатить)\b", "signal_budget_ready"),
    _r("SIG-DUE-001", 410, "deadline_present", "deadline", 5, r"\b(?:срок|дедлайн)\b\s*(?:[:=—-]\s*)?(?:до\s*)?\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?", "signal_deadline_date"),
    _r("SIG-DUE-002", 411, "deadline_present", "deadline", 4, r"\b(?:за|в течение)\s+\d+\s+(?:час(?:а|ов)?|дн(?:я|ей)|недел(?:ю|и|ь)|месяц(?:а|ев)?)\b", "signal_deadline_period"),
    _r("SIG-URG-001", 420, "urgency_present", "urgency", 5, r"\b(?:срочно|очень срочно|как можно быстрее|asap|горит)\b", "signal_urgency"),
    _r("SIG-STA-001", 430, "ready_to_start", "readiness", 5, r"\b(?:готов начать|готовы начать|можем начать|стартуем|начать сразу|приступить сегодня)\b", "signal_ready_start"),
    _r("SIG-CON-001", 440, "contact_present", "contactability", 3, r"(?<![\w@])@[a-z0-9_]{5,32}\b", "signal_contact_username"),
    _r("SIG-CON-002", 441, "contact_present", "contactability", 4, r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", "signal_contact_email"),
    _r("SIG-CON-003", 442, "contact_present", "contactability", 4, r"(?<!\d)(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)", "signal_contact_phone"),
    _r("SIG-SPC-001", 450, "task_specificity", "specificity", 10, r"\b(?:нужно|задача|тз)\b.{0,160}\b(?:для|чтобы|с функцией|который|которая|интеграция с)\b", "signal_task_detail"),
    _r("SIG-SPC-002", 451, "task_specificity", "specificity", 8, r"\b(?:оплата|авторизация|личный кабинет|админ(?:ка|панель)|каталог|корзина|уведомления|выгрузка|синхронизация)\b", "signal_task_feature"),
)


def catalog_canonical_json() -> str:
    payload = [
        {
            "stable_rule_id": r.stable_rule_id,
            "priority": r.priority,
            "target": r.target,
            "dimension": r.dimension,
            "weight": r.weight,
            "pattern": r.pattern,
            "explanation_code": r.explanation_code,
            "kind": r.kind,
            "flags": RULE_FLAGS,
            "enabled": True,
        }
        for r in SEED_RULES
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def catalog_checksum() -> str:
    return hashlib.sha256(catalog_canonical_json().encode("utf-8")).hexdigest()


async def seed_ruleset_ru_mvp_1(session: AsyncSession) -> RuleSetVersion:
    checksum = catalog_checksum()
    existing = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.slug == "ru-mvp-1")
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        if row.checksum != checksum:
            raise RuntimeError("ruleset_checksum_mismatch")
        return row

    await session.execute(
        update(RuleSetVersion).where(RuleSetVersion.state == "active").values(state="retired")
    )
    now = datetime.now(UTC)
    version = RuleSetVersion(
        version=1,
        slug="ru-mvp-1",
        locale="ru",
        state="active",
        checksum=checksum,
        hot_min=70,
        warm_min=50,
        cold_min=30,
        activated_at=now,
    )
    session.add(version)
    await session.flush()
    for rule in SEED_RULES:
        rule_checksum = hashlib.sha256(
            json.dumps(asdict(rule), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        session.add(
            MonitoringRule(
                rule_set_version_id=version.id,
                stable_rule_id=rule.stable_rule_id,
                kind=rule.kind,
                target=rule.target,
                dimension=rule.dimension,
                weight=rule.weight,
                pattern=rule.pattern,
                flags=RULE_FLAGS,
                priority=rule.priority,
                explanation_code=rule.explanation_code,
                enabled=True,
                checksum=rule_checksum,
            )
        )
    await session.flush()
    return version


async def get_active_ruleset(session: AsyncSession) -> RuleSetVersion | None:
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.state == "active").limit(1)
    )
    return result.scalar_one_or_none()


async def seed_active_ruleset(session: AsyncSession) -> RuleSetVersion:
    return await seed_ruleset_ru_mvp_1(session)

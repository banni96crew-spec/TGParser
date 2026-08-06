"""Version assembly for immutable detection catalogs."""

from telegram_lead_discovery.detection.catalog_types import SeedRule, _r
from telegram_lead_discovery.detection.catalog_v1 import SEED_RULES


_REMEDIATION_RULES_V2: tuple[SeedRule, ...] = (
    _r(
        "NEG-ADV-004",
        123,
        "advertising",
        "hard_exclusion",
        0,
        r"(?:#помогу|\bпомогу\b).{0,60}\b(?:сайт|лендинг|бот|tilda|тильда|интеграц|парсер|магазин)\b",
        "advertising_help_hashtag",
    ),
    _r(
        "NEG-ADV-005",
        124,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:разработчик(?:а)? сайтов?|веб[- ]?мастер|фрилансер)\b.{0,100}\b(?:под ключ|портфолио|опыт\s+\d+|в наличии|свободн(?:а|ы)?\s+для\s+заказов)\b",
        "advertising_portfolio_offer",
    ),
    _r(
        "NEG-ADV-006",
        125,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:сделаю|делаю|разработаю|создам|настрою)\b.{0,50}\b(?:сайт|лендинг|бот|магазин|интеграц|парсер)\b",
        "advertising_first_person_offer",
    ),
    _r(
        "SVC-ECOM-003",
        242,
        "ecommerce",
        "service_fit",
        10,
        r"\b(?:снять|отснять|сфотографировать|фотосесси(?:я|ю)|фото)\b.{0,80}\b(?:интерьер|товар(?:ы|ов)?|каталог).{0,60}\b(?:для сайта|для магазина|для интернет[- ]?магазина|для карточек)\b",
        "service_ecommerce_product_photo",
    ),
    _r(
        "POS-DIR-005",
        304,
        "direct_order",
        "intent",
        14,
        r"\b(?:нужно|надо|хочу|хотим|требуется)\b.{0,80}\b(?:снять|отснять|сфотографировать|фотосесси(?:я|ю)|сделать фото)\b",
        "intent_direct_photo",
    ),
)

SEED_RULES_RU_MVP_2: tuple[SeedRule, ...] = SEED_RULES + _REMEDIATION_RULES_V2

# Run14 precision remediation: provider cards, resumes, vacancies, marketplace news/ops.
# Do not broadly ban all marketplace or first-person language (DET-018).
_REMEDIATION_RULES_V3: tuple[SeedRule, ...] = (
    _r(
        "NEG-ADV-007",
        126,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:разрабатываю|пишу|занимаюсь)\b.{0,120}\b(?:telegram[- ]?бот|телеграм[- ]?бот|бот(?:ов|ы)?|сайт|парсер|карточек|инфографик).{0,160}\b(?:готовые кейсы|портфолио|могу показать|есть готовые|кейсы:)\b",
        "advertising_provider_cases",
    ),
    _r(
        "NEG-ADV-008",
        127,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:нужны кому[- ]?то услуги|кому нужны услуги|услуги разработчика\s*\?)\b",
        "advertising_service_solicitation",
    ),
    _r(
        "NEG-ADV-009",
        128,
        "advertising",
        "hard_exclusion",
        0,
        r"(?:#специалист|\bчто умею\b|\bопыт работы с\s+\d{4}|\bпомогаю брендам\b|\bменеджер маркетплейсов\b)",
        "advertising_specialist_card",
    ),
    _r(
        "NEG-ADV-010",
        129,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:откликаюсь на вакансию|откликнулся на вакансию)\b",
        "advertising_job_seeker_resume",
    ),
    _r(
        "NEG-ADV-011",
        130,
        "advertising",
        "hard_exclusion",
        0,
        r"\bкому нужен бухгалтер\b",
        "advertising_out_of_scope_referral",
    ),
    _r(
        "NEG-ADV-012",
        131,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:платит селлерам|атак(?:и|а|ам|ами)? на склад|перераспределяет поток|оферта говорит|пожаров? на склад)\b",
        "advertising_marketplace_news",
    ),
    _r(
        "NEG-ADV-013",
        132,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:перераспределени[еюя]\s+остатков|подключить перераспределение)\b",
        "advertising_marketplace_ops",
    ),
    _r(
        "NEG-ADV-014",
        133,
        "advertising",
        "hard_exclusion",
        0,
        r"\b(?:мне )?нужно отгрузить\b|\bотгрузить текущие заказы\b",
        "advertising_operational_shipping",
    ),
    _r(
        "NEG-ADV-015",
        134,
        "advertising",
        "hard_exclusion",
        0,
        r"\bзанимаюсь оформлением карточек\b",
        "advertising_card_design_offer",
    ),
    _r(
        "NEG-VAC-006",
        145,
        "vacancy",
        "hard_exclusion",
        0,
        r"(?:\b(?:удалёнка|удаленка)\b.{0,40}\b(?:support|поддержк))|(?:\bищем\b.{0,40}\b(?:специалист(?:ов)?|сотрудник(?:ов)?|менеджер(?:ов)?)\b)",
        "vacancy_support_hiring",
    ),
)

SEED_RULES_RU_MVP_3: tuple[SeedRule, ...] = SEED_RULES_RU_MVP_2 + _REMEDIATION_RULES_V3
ACTIVE_SEED_RULES: tuple[SeedRule, ...] = SEED_RULES_RU_MVP_3


__all__ = [
    "ACTIVE_SEED_RULES",
    "RULE_FLAGS",
    "SEED_RULES",
    "SEED_RULES_RU_MVP_2",
    "SEED_RULES_RU_MVP_3",
    "SeedRule",
]

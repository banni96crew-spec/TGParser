# Модульный PRD 04 — Lead Detection

## 1. Назначение и границы

Модуль детерминированно определяет категорию сообщения, соответствующие услуги и признаки запроса с помощью immutable versioned rule sets. Результат содержит matched rule IDs и короткое шаблонное объяснение. AI/LLM отсутствуют.

Модуль не вычисляет итоговый score и не получает сообщения из Telegram.

## 2. Goals и non-goals

### Goals

- Отделять потенциальные запросы от вакансий, рекламы, спама и нерелевантного текста.
- Обеспечить воспроизводимость результата по message revision и rule-set version.
- Защитить pipeline от зависающих regex.
- Поддерживать пять фиксированных service profiles.
- Объяснять каждый результат точными IDs совпавших правил.

### Non-goals

- AI/LLM, embeddings и внешние classification API.
- Автоматическое обучение на действиях оператора.
- Анализ изображений, документов, аудио и video.
- Мультиязычная классификация.
- Вычисление score и score band.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Engine | Python-библиотека `regex` |
| Начальная version | `ru-mvp-1`, integer version `1` |
| Хранение | SQLite, immutable active versions |
| Seed | Alembic data migration/seed command |
| Runtime flags | `IGNORECASE | FULLCASE | VERSION1` |
| Timeout одного pattern | `50 ms` |
| Activation performance gate | Каждый pattern не более `25 ms` на stress corpus |
| Анализируемый текст | Первые `4096` Unicode code points |
| Rule order | `priority ASC`, затем `rule_id ASC` |
| Hard-exclusion precedence | `spam`, затем `advertising`, затем `vacancy` |
| Positive precedence | `direct_order`, `contractor_search`, `recommendation_request`, `potential_need` |

Категории:

- положительные: `direct_order`, `contractor_search`, `recommendation_request`, `potential_need`;
- отрицательные: `vacancy`, `advertising`, `spam`, `irrelevant`.

Service profiles: `websites`, `telegram_bots`, `integrations_api`, `automation_parsers`, `ecommerce`.

## 4. Versioned rule engine

### DET-001 — Immutable versions

`RuleSetVersion` содержит integer version, slug, locale, status `draft|active|retired`, checksum, created/activated timestamps. После activation rules и metadata version MUST быть immutable. Изменение создаёт следующую integer version.

Ровно одна version имеет status `active`. Activation новой version и retirement прежней выполняются одной SQLite-транзакцией.

### DET-002 — Rule schema

Rule MUST содержать:

- `rule_id` — стабильный ASCII ID;
- `rule_set_version_id`;
- `kind`: `hard_exclusion`, `service`, `positive_intent`, `signal`;
- `target` — category, service profile или signal name;
- `dimension` — score/exclusion dimension (D-041);
- `weight` — целое contribution weight (для hard exclusion — `0`);
- `pattern`;
- `priority` integer;
- `explanation_code`;
- `enabled` boolean;
- `checksum`.

В version `ru-mvp-1` все правила из DET-A имеют `enabled=true`, а `dimension`/`weight` равны нормативным значениям приложения DET-A.

### DET-003 — Validation и activation

До activation система MUST:

1. скомпилировать каждый pattern с утверждёнными flags;
2. отклонить duplicate rule ID;
3. отклонить пустой pattern/target/explanation code;
4. выполнить positive, negative и stress fixtures;
5. проверить runtime каждого pattern на stress corpus с limit `25 ms`;
6. вычислить SHA-256 checksum канонического JSON всех rules, отсортированных по rule ID.

Любая ошибка блокирует activation без изменения текущей active version.

### DET-004 — Evaluation

Engine получает `analysis_text`, уже нормализованный PROC-003. Rules выполняются по `priority ASC, rule_id ASC`. Каждый вызов `regex.search` получает timeout `0.05` секунды.

### DET-005 — Regex timeout

Timed-out rule считается `not matched`, фиксируется в `timed_out_rule_ids`, создаётся metric/event, а обработка остальных правил продолжается. Detection outcome получает `completed_with_timeout`. Rule-set version с десятью timeout results в течение любых `5 минут` автоматически не деактивируется; Collector/processing продолжают работу, а health Detection становится `degraded`.

### DET-006 — Version binding

Processing job сохраняет active rule-set version ID до начала evaluation. Результат всегда ссылается на эту version даже при одновременной activation новой. Новая version применяется к новым jobs; история пересчитывается только explicit manual replay.

## 5. Category algorithm

### DET-007 — Hard exclusions

Если совпало хотя бы одно hard-exclusion rule, итоговая категория выбирается по precedence `spam > advertising > vacancy`. Positive rules не влияют на итог, но service matches сохраняются для диагностики. Результат `is_lead=false`.

### DET-008 — Service matching

Все service rules вычисляются независимо. Result сохраняет отсортированный уникальный список profiles. Positive category требует минимум один service profile, кроме прямого правила `POS-DIR-004` с техническим action phrase, которое само задаёт profile из совпавшего service term.

### DET-009 — Positive category

При отсутствии hard exclusion engine вычисляет positive intent rules. Для итоговой категории требуется хотя бы один positive intent match и хотя бы один service match. Если совпало несколько категорий, используется precedence `direct_order > contractor_search > recommendation_request > potential_need`.

### DET-010 — Irrelevant fallback

Если hard exclusion и полноценная positive pair отсутствуют, категория равна `irrelevant`, `is_lead=false`.

### DET-011 — Result

`DetectionResult` MUST содержать message revision ID, rule-set version ID/checksum, category, `is_lead`, service profiles, `matched_rules[]` (`stable_rule_id`, `rule_type`, `dimension`, `weight`, `matched_excerpt` ≤120 Unicode code points), timed-out IDs, explanation codes, exact explanation text, duration и created timestamp.

### DET-012 — Explanation

Explanation строится без свободной генерации:

| Категория | Шаблон |
|---|---|
| `direct_order` | `Прямой запрос на услугу: {services}. Совпали правила: {rule_ids}.` |
| `contractor_search` | `Автор ищет исполнителя: {services}. Совпали правила: {rule_ids}.` |
| `recommendation_request` | `Автор запрашивает рекомендацию специалиста: {services}. Совпали правила: {rule_ids}.` |
| `potential_need` | `Обнаружена потенциальная техническая потребность: {services}. Совпали правила: {rule_ids}.` |
| `vacancy` | `Сообщение классифицировано как вакансия. Совпали правила: {rule_ids}.` |
| `advertising` | `Сообщение классифицировано как реклама услуг. Совпали правила: {rule_ids}.` |
| `spam` | `Сообщение классифицировано как спам. Совпали правила: {rule_ids}.` |
| `irrelevant` | `Не найдено сочетание запроса и поддерживаемой услуги.` |

Services выводятся в порядке `websites`, `telegram_bots`, `integrations_api`, `automation_parsers`, `ecommerce`; rule IDs — ASCII sort. Excerpt исходного текста в explanation отсутствует.

## 6. Signals для scoring

### DET-013 — Signal extraction

Engine MUST публиковать boolean signals: `budget_present`, `deadline_present`, `urgency_present`, `ready_to_start`, `contact_present`, `task_specificity`. Signals определяются только правилами DET-A. Значения бюджета, телефона или email отдельно не интерпретируются этим модулем.

### DET-014 — Multiple matches

Все matched signal rule IDs сохраняются, но каждое boolean signal устанавливается один раз. Повторение фразы не увеличивает score.

### DET-015 — Reuse для keyword scouting

Detection engine MUST предоставлять pure evaluation entrypoint (тот же алгоритм DET-004..DET-014), принимающий `analysis_text`, `rule_set_version_id` и checksum без обязательной `message_revision_id` pipeline binding. SRC keyword scouting MAY вызывать этот entrypoint для классификации evidence. Вызов MUST NOT создавать Lead pipeline side effects: не пишет `TelegramMessage`/`ProcessingResult` lead-path и не эмитит `LeadDetected` outbox для scouting (D-052). Результат для scouting сохраняется владельцем SRC в `SourceDiscoveryEvidence`.

### DET-016 — Runtime loader by version + checksum; bootstrap-only seed

Runtime loader MUST fetch immutable compiled catalog from DB/cache keyed by **checksum** for the pinned `rule_set_version_id` (D-065). Missing version or checksum mismatch → permanent processing error / dead-letter (`RULE_SET_INVALID` / equivalent) — **no** `SEED_RULES` silent fallback. `SEED_RULES` allowed **only** when creating the initial DB version at bootstrap/migration. Regex timeout **50 ms**; input cap **4096** characters; compile cache key = checksum; byte-stable result for same revision+version (NFR-QLT-005).

### DET-017 — Remediation catalog `ru-mvp-2` (D-068 / NFR-QLT-007)

Provider self-promotion (`#Помогу`, «под ключ»/portfolio offers, first-person «сделаю/делаю сайт») MUST hard-exclude as `advertising` without breaking true client intents. Commercial product/interior photography for a website/shop MUST classify as client intent with `ecommerce` (+ typically `websites`). Activation MUST create new immutable `RuleSetVersion` slug `ru-mvp-2` and retire prior active version — never mutate `ru-mvp-1`. Versioned labeled corpus MUST demonstrate precision ≥ `0.80` and recall ≥ `0.80` with honest sample metadata: C01–C20 are sanitized derivatives of operator run-13 evidence (owner labels; 3 positives / 17 negatives — too small alone for population inference); T1–T5 are DET-A synthetic golden positives (`det_a_golden`), not live Telegram text. Reports MUST show live-only and combined confusion matrices separately.

### DET-018 — Run14 precision remediation catalog `ru-mvp-3`

Active catalog MUST advance to immutable `ru-mvp-3` = `ru-mvp-2` plus explainable hard exclusions for confirmed run14 false positives: provider self-promo with cases/portfolio, service solicitations, specialist/resume cards (`#специалист`, «что умею», marketplace manager cards), job-seeker resumes, out-of-scope referrals (accountant), marketplace news/ops commentary, operational shipping chatter, and support-hiring vacancies — without broadly excluding all marketplace language or all first-person text, and without losing the plausible automation-need ask. Regex timeout/`4096` input cap MUST remain. Reports MUST separate metrics for: live C01–C20, run14 regression (`operator_run_14_sanitized_excerpt`, not population), golden T*, and combined. Do not claim population readiness from fixtures.

### DET-019 — Active-client intent catalog `ru-mvp-4` (D-070)

Active catalog MUST advance to immutable `ru-mvp-4` = `ru-mvp-3` plus narrowly scoped rules for explicit client orders, searches for a contractor and requests for a recommendation across all five service profiles. New stable rules MUST distinguish a buyer phrase (`нужен|ищу|требуется|посоветуйте|порекомендуйте` + contractor/action + supported service) from a provider offer, portfolio/case card, vacancy/resume, marketplace news, shipping/orders/support chatter and course content. Bare `WB|Wildberries|Ozon|маркетплейс|заказы|доставка|отгрузка|поддержка` MUST NOT by itself establish a development service. Existing `potential_need` remains available to the Lead pipeline but SRC ActiveClientChat v1 excludes it from countable requests. `ru-mvp-1..3` and their checksums remain immutable. C*, R14, T* and new boundary fixtures MUST be reported separately; combined precision and recall remain ≥`0.80` under NFR-QLT-007.

## 7. Data ownership и contracts

Модуль владеет `RuleSetVersion`, `ServiceProfile`, `KeywordGroup`, `MonitoringRule`, `DetectionResult`, `MatchedRule`. Message Processing владеет message revision; Lead Scoring потребляет immutable DetectionResult; Source Discovery потребляет pure detect для scouting text.

Команда:

```text
DetectLead(message_revision_id, analysis_text, rule_set_version_id)
  -> DetectionResult

DetectAnalysisText(analysis_text, rule_set_version_id)
  -> DetectionEvaluation (category, hard_exclusion, matched_rules, service_profiles, explanation)
```

Published events (только pipeline path с revision):

- `LeadDetected`: result ID, revision ID, category, services, signals, version ID;
- `MessageExcluded`: result ID, revision ID, negative category, version ID;
- `DetectionRuleTimedOut`: result ID, rule ID, version ID, duration;
- `DetectionCompleted`: result ID, outcome, duration.

Все mutations processing result/outbox выполняются одной транзакцией владельца pipeline. Scouting path не публикует эти events.

## 8. Errors, retry и recovery

- Invalid active version переводит Detection health в `blocked`; job получает permanent error `RULE_SET_INVALID`.
- Runtime timeout обрабатывается по DET-005 и не вызывает retry.
- SQLite transient error повторяется Message Processing по его fixed retry schedule.
- Неожиданная engine exception создаёт `DETECTION_ENGINE_ERROR` и повторяется Message Processing.
- Один и тот же revision/version pair имеет unique result; replay с той же pair возвращает существующий result, если explicit force flag отсутствует.

## 9. Security requirements

- Pattern создаётся только локальным оператором и проходит compile/performance gate.
- Каждый regex вызов имеет timeout `50 ms` и текст максимум `4096` code points.
- Message text и matched substrings отсутствуют в logs/metrics.
- UI HTML-экранирует pattern и explanation.
- Seed checksum проверяется после migration и при startup.

## 10. Observability

Metrics:

- `detection_results_total{category,version,outcome}`;
- `detection_duration_seconds{version}`;
- `detection_rule_matches_total{rule_id,version}`;
- `detection_rule_timeouts_total{rule_id,version}`;
- `detection_service_matches_total{service,version}`;
- `detection_irrelevant_total{version}`.

Structured log содержит result/revision/version IDs, category, matched rule IDs, duration и error code; message text отсутствует.

## 11. Dependencies

- `01-source-discovery`: consumer pure detect для keyword scouting evidence.
- `03-message-processing`: eligible revision и version binding.
- `05-lead-scoring`: потребитель positive result/signals.
- `06-lead-storage`: versioned rules/results.
- `07-lead-dashboard`: explanation и rule management UI.
- `09-operator-settings`: активная version reference.
- `10-administration-observability`: health, metrics и replay visibility.

## 12. MVP и исключённые функции

MVP включает DET-001—DET-019 и приложение DET-A. Исключены AI/LLM, embeddings, automatic learning, fuzzy rules, multilingual rules и автоматическая activation.

## 13. Acceptance criteria и test catalogue

| ID | Requirement | Сценарий | Ожидаемый результат |
|---|---|---|---|
| `AT-DET-001` | DET-001 | Попытаться изменить active rule | Изменение отклонено; требуется новая version |
| `AT-DET-002` | DET-002 | Загрузить seed `ru-mvp-1` | Все DET-A rules сохранены с `dimension`+`weight` |
| `AT-DET-003` | DET-003 | Добавить invalid/slow regex | Activation заблокирована |
| `AT-DET-004` | DET-004 | Повторить corpus в 100 прогонах | Matched IDs и category идентичны |
| `AT-DET-005` | DET-005 | Fake rule превышает 50 ms | Rule пропущен, result completed_with_timeout |
| `AT-DET-006` | DET-006 | Активировать v2 во время job v1 | Result ссылается на v1 |
| `AT-DET-007` | DET-007 | Текст совпадает vacancy и contractor | Итог vacancy, lead=false |
| `AT-DET-008` | DET-008 | Текст содержит сайт и Telegram-бот | Сохранены оба profiles в заданном порядке |
| `AT-DET-009` | DET-009 | Совпали direct и contractor | Итог direct_order |
| `AT-DET-010` | DET-010 | Есть service без intent | Итог irrelevant |
| `AT-DET-011` | DET-011 | Проверить result schema | Все IDs, version, matches с `weight`/`dimension`/`matched_excerpt`≤120 и duration присутствуют |
| `AT-DET-012` | DET-012 | Повторить один fixture | Explanation byte-for-byte идентично |
| `AT-DET-013` | DET-013 | Fixture содержит бюджет, срок, контакт | Три boolean signals true |
| `AT-DET-014` | DET-014 | Бюджет указан дважды | Один boolean signal и два matched IDs без усиления |
| `AT-DET-015` | DET-015 | Вызвать DetectAnalysisText из scouting fixture | Category совпадает с DetectLead на том же тексте; Lead/outbox не созданы |
| `AT-DET-016` | DET-016 | Runtime load with wrong checksum; bootstrap seed path | RULE_SET_INVALID / no silent SEED_RULES fallback; seed only at bootstrap |
| `AT-DET-017` | DET-017 | Live run13 C01–C20 sanitized + DET-A T1–T5 golden; provenance split | `ru-mvp-2`; C02–C04 advertising; C01/C05 same normalized client; C06 ecommerce; C07–C20 live negatives; T* not labeled live; live-only + combined ≥80/80 reported separately |
| `AT-DET-018` | DET-018 | Run14 sanitized FP regression + keep automation ask; C/T unchanged ≥80/80 | `ru-mvp-3`; FPs hard-excluded; KEEP retained; separate C* / R14 / T* / combined metrics; provenance `operator_run_14_sanitized_excerpt` |
| `AT-DET-019` | DET-019 | Paired buyer/provider/vacancy/marketplace-ops fixtures for every service family | `ru-mvp-4`; explicit buyers retain direct/contractor/recommendation; provider and operational chatter excluded; bare marketplace tokens do not establish service; separate reports and combined ≥80/80 |

Golden classification fixtures:

| Текст | Итог |
|---|---|
| `Нужно разработать интернет-магазин, бюджет 150 000 ₽.` | `direct_order`, `ecommerce`, budget |
| `Ищу разработчика Telegram-бота для приёма заказов.` | `contractor_search`, `telegram_bots` |
| `Посоветуйте специалиста по интеграции сайта с CRM.` | `recommendation_request`, `websites + integrations_api` |
| `Как автоматизировать перенос заказов из магазина в CRM?` | `potential_need`, `automation_parsers + ecommerce + integrations_api` |
| `Вакансия: Python-разработчик в штат, зарплата 200000.` | `vacancy` |
| `Наша команда разрабатывает сайты, скидка до пятницы.` | `advertising` |
| `Гарантированный заработок в крипте, пишите всем.` | `spam` |
| `Сегодня отличная погода.` | `irrelevant` |
| `#Помогу с сайтом на Tilda` | `advertising` (ru-mvp-2) |
| `Разработчик сайтов под ключ, портфолио в наличии` | `advertising` (ru-mvp-2) |
| `Сделаю сайт / лендинг под ключ` | `advertising` (ru-mvp-2) |
| `Нужно снять интерьер для сайта 6000₽ по завершению` | `direct_order`, `ecommerce` (+websites) (ru-mvp-2) |

## 14. Принятые записи decision log

- `DEC-DET-001`: только rule-based RU engine без AI/LLM.
- `DEC-DET-002`: engine `regex`, runtime timeout 50 ms, analysis limit 4096 code points.
- `DEC-DET-003`: active rules immutable; изменение создаёт version.
- `DEC-DET-004`: hard exclusions выполняются до positive rules.
- `DEC-DET-005`: нормативный начальный catalog равен DET-A.
- `D-068`: historical remediation `ru-mvp-2` provider-offer exclusions + ecommerce product-photo semantics (`DET-017`).
- `D-070`: immutable `ru-mvp-4`, explicit buyer intent and marketplace operational-noise boundary (`DET-019`).

---

# Приложение DET-A — нормативный RU catalog

`ru-mvp-1` / `ru-mvp-2` / `ru-mvp-3` remain immutable historical seeds. Active catalog after D-070 is `ru-mvp-4` = `ru-mvp-3` plus the exact DET-019 additions listed after the v3 block. Tables below list the full `ru-mvp-2` normative set; v3 and v4 additions are listed after.

## A.1 Общие правила исполнения

- Все patterns применяются к `analysis_text` из PROC-003.
- Flags: `regex.IGNORECASE | regex.FULLCASE | regex.VERSION1`.
- Search timeout: `0.05` секунды.
- Priority ranges: hard exclusions `100–199`, services `200–299`, positive intents `300–399`, signals `400–499`.
- В таблицах pattern является точной строкой, сохраняемой в SQLite без дополнительного macro expansion.

## A.2 Hard exclusions

Нормативные строки ниже заключены в code block, поэтому символ `|` внутри pattern является частью regex без Markdown-экранирования. Формат строки: `Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code`.

```text
| Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code |
|---|---:|---|---|---:|---|---|
| `NEG-SPAM-001` | 100 | `spam` | `hard_exclusion` | 0 | `\b(?:казино|слоты|ставки на спорт|букмекер|джекпот)\b` | `spam_gambling` |
| `NEG-SPAM-002` | 101 | `spam` | `hard_exclusion` | 0 | `\b(?:гарантированный заработок|быстрый заработок|доход без вложений|крипто[- ]?сигналы|раздача криптовалюты)\b` | `spam_income` |
| `NEG-SPAM-003` | 102 | `spam` | `hard_exclusion` | 0 | `\b(?:рассылка по чатам|массовая рассылка|накрутка подписчиков|накрутка реакций)\b` | `spam_bulk` |
| `NEG-ADV-001` | 120 | `advertising` | `hard_exclusion` | 0 | `\b(?:мы|наша команда|наше агентство)\b.{0,80}\b(?:делаем|разрабатываем|создаём|оказываем|предлагаем)\b` | `advertising_provider` |
| `NEG-ADV-002` | 121 | `advertising` | `hard_exclusion` | 0 | `\b(?:скидка|акция|спецпредложение|специальное предложение)\b.{0,80}\b(?:на сайт|на разработку|на бота|на услуги|до пятницы|до конца месяца)\b` | `advertising_promo` |
| `NEG-ADV-003` | 122 | `advertising` | `hard_exclusion` | 0 | `\b(?:принимаем заказы|свободны для новых проектов|возьмём ваш проект|закажите у нас)\b` | `advertising_solicitation` |
| `NEG-ADV-004` | 123 | `advertising` | `hard_exclusion` | 0 | `(?:#помогу|\bпомогу\b).{0,60}\b(?:сайт|лендинг|бот|tilda|тильда|интеграц|парсер|магазин)\b` | `advertising_help_hashtag` |
| `NEG-ADV-005` | 124 | `advertising` | `hard_exclusion` | 0 | `\b(?:разработчик(?:а)? сайтов?|веб[- ]?мастер|фрилансер)\b.{0,100}\b(?:под ключ|портфолио|опыт\s+\d+|в наличии|свободн(?:а|ы)?\s+для\s+заказов)\b` | `advertising_portfolio_offer` |
| `NEG-ADV-006` | 125 | `advertising` | `hard_exclusion` | 0 | `\b(?:сделаю|делаю|разработаю|создам|настрою)\b.{0,50}\b(?:сайт|лендинг|бот|магазин|интеграц|парсер)\b` | `advertising_first_person_offer` |
| `NEG-ADV-007` | 126 | `advertising` | `hard_exclusion` | 0 | `\b(?:разрабатываю|пишу|занимаюсь)\b.{0,120}\b(?:telegram[- ]?бот|телеграм[- ]?бот|бот(?:ов|ы)?|сайт|парсер|карточек|инфографик).{0,160}\b(?:готовые кейсы|портфолио|могу показать|есть готовые|кейсы:)\b` | `advertising_provider_cases` |
| `NEG-ADV-008` | 127 | `advertising` | `hard_exclusion` | 0 | `\b(?:нужны кому[- ]?то услуги|кому нужны услуги|услуги разработчика\s*\?)\b` | `advertising_service_solicitation` |
| `NEG-ADV-009` | 128 | `advertising` | `hard_exclusion` | 0 | `(?:#специалист|\bчто умею\b|\bопыт работы с\s+\d{4}|\bпомогаю брендам\b|\bменеджер маркетплейсов\b)` | `advertising_specialist_card` |
| `NEG-ADV-010` | 129 | `advertising` | `hard_exclusion` | 0 | `\b(?:откликаюсь на вакансию|откликнулся на вакансию)\b` | `advertising_job_seeker_resume` |
| `NEG-ADV-011` | 130 | `advertising` | `hard_exclusion` | 0 | `\bкому нужен бухгалтер\b` | `advertising_out_of_scope_referral` |
| `NEG-ADV-012` | 131 | `advertising` | `hard_exclusion` | 0 | `\b(?:платит селлерам|атак(?:и|а|ам|ами)? на склад|перераспределяет поток|оферта говорит|пожаров? на склад)\b` | `advertising_marketplace_news` |
| `NEG-ADV-013` | 132 | `advertising` | `hard_exclusion` | 0 | `\b(?:перераспределени[еюя]\s+остатков|подключить перераспределение)\b` | `advertising_marketplace_ops` |
| `NEG-ADV-014` | 133 | `advertising` | `hard_exclusion` | 0 | `\b(?:мне )?нужно отгрузить\b|\bотгрузить текущие заказы\b` | `advertising_operational_shipping` |
| `NEG-ADV-015` | 134 | `advertising` | `hard_exclusion` | 0 | `\bзанимаюсь оформлением карточек\b` | `advertising_card_design_offer` |
| `NEG-VAC-001` | 140 | `vacancy` | `hard_exclusion` | 0 | `\b(?:вакансия|открыта позиция|открыта вакансия|ищем сотрудника)\b` | `vacancy_marker` |
| `NEG-VAC-002` | 141 | `vacancy` | `hard_exclusion` | 0 | `\b(?:в штат|полная занятость|частичная занятость|оформление по тк|трудоустройство)\b` | `vacancy_employment` |
| `NEG-VAC-003` | 142 | `vacancy` | `hard_exclusion` | 0 | `\b(?:зарплата|оклад)\b\s*(?:от\s*)?\d[\d\s]{2,}` | `vacancy_salary` |
| `NEG-VAC-004` | 143 | `vacancy` | `hard_exclusion` | 0 | `(?:https?://)?(?:www\.)?(?:hh\.ru|career\.habr\.com)/\S+` | `vacancy_link` |
| `NEG-VAC-005` | 144 | `vacancy` | `hard_exclusion` | 0 | `\b(?:присылайте резюме|отправляйте резюме|откликнуться на вакансию|испытательный срок)\b` | `vacancy_application` |
| `NEG-VAC-006` | 145 | `vacancy` | `hard_exclusion` | 0 | `(?:\b(?:удалёнка|удаленка)\b.{0,40}\b(?:support|поддержк))|(?:\bищем\b.{0,40}\b(?:специалист(?:ов)?|сотрудник(?:ов)?|менеджер(?:ов)?)\b)` | `vacancy_support_hiring` |
```

## A.3 Service profiles

```text
| Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code |
|---|---:|---|---|---:|---|---|
| `SVC-WEB-001` | 200 | `websites` | `service_fit` | 12 | `\b(?:сайт(?:а|е|ом|у|ы|ов)?|лендинг(?:а|е|и|ов)?|веб[- ]?приложени(?:е|я|ю|ем|й)|frontend|backend|фронтенд|бэкенд)\b` | `service_websites` |
| `SVC-WEB-002` | 201 | `websites` | `service_fit` | 8 | `\b(?:wordpress|tilda|webflow|react|vue|django|fastapi)\b` | `service_web_stack` |
| `SVC-BOT-001` | 210 | `telegram_bots` | `service_fit` | 12 | `\b(?:telegram|телеграм|тг)\b.{0,30}\b(?:бот(?:а|е|ом|у|ы|ов)?|mini app|мини[- ]?приложени(?:е|я))\b` | `service_telegram_bot` |
| `SVC-BOT-002` | 211 | `telegram_bots` | `service_fit` | 8 | `\b(?:чат[- ]?бот(?:а|ы|ов)?|бот для (?:заказов|оплаты|поддержки|записи))\b` | `service_chatbot` |
| `SVC-INT-001` | 220 | `integrations_api` | `service_fit` | 12 | `\b(?:интеграц(?:ия|ии|ию|ией)|api|апи|webhook|вебхук)\b` | `service_integration` |
| `SVC-INT-002` | 221 | `integrations_api` | `service_fit` | 8 | `\b(?:crm|amo ?crm|битрикс ?24|1с|мой ?склад)\b` | `service_business_system` |
| `SVC-AUT-001` | 230 | `automation_parsers` | `service_fit` | 12 | `\b(?:автоматизац(?:ия|ии|ию|ией)|автоматизировать|автоматизируем|автоматизируется|парсер(?:а|ы|ов)?|парсинг|скрейпинг|scraping)\b` | `service_automation` |
| `SVC-AUT-002` | 231 | `automation_parsers` | `service_fit` | 8 | `\b(?:сбор данных|выгрузка данных|обработка данных|перенос данных)\b` | `service_data_flow` |
| `SVC-ECOM-001` | 240 | `ecommerce` | `service_fit` | 12 | `\b(?:интернет[- ]?магазин(?:а|е|ы|ов)?|e[- ]?commerce|электронн(?:ая|ой) коммерци(?:я|и))\b` | `service_ecommerce` |
| `SVC-ECOM-002` | 241 | `ecommerce` | `service_fit` | 8 | `\b(?:маркетплейс(?:а|е|ы|ов)?|wildberries|ozon|яндекс маркет|товарн(?:ый|ого) каталог|корзин(?:а|ы)|перенос заказов|обработка заказов|приём заказов)\b` | `service_marketplace` |
| `SVC-ECOM-003` | 242 | `ecommerce` | `service_fit` | 10 | `\b(?:снять|отснять|сфотографировать|фотосесси(?:я|ю)|фото)\b.{0,80}\b(?:интерьер|товар(?:ы|ов)?|каталог).{0,60}\b(?:для сайта|для магазина|для интернет[- ]?магазина|для карточек)\b` | `service_ecommerce_product_photo` |
```

## A.4 Positive intent

```text
| Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code |
|---|---:|---|---|---:|---|---|
| `POS-DIR-001` | 300 | `direct_order` | `intent` | 15 | `\b(?:нужно|надо|хочу|хотим|планирую|планируем)\b.{0,100}\b(?:сделать|разработать|создать|доработать|исправить|настроить|подключить|интегрировать|автоматизировать|перенести|запустить)\b` | `intent_direct_need` |
| `POS-DIR-002` | 301 | `direct_order` | `intent` | 15 | `\b(?:задача|тз|техническое задание)\b.{0,100}\b(?:сделать|разработать|создать|доработать|исправить|настроить|подключить|интегрировать|автоматизировать)\b` | `intent_direct_task` |
| `POS-DIR-003` | 302 | `direct_order` | `intent` | 12 | `\b(?:кто|кто-нибудь|кто-то)\b.{0,60}\b(?:сделает|разработает|создаст|доработает|настроит|подключит|интегрирует|автоматизирует)\b` | `intent_direct_who` |
| `POS-DIR-004` | 303 | `direct_order` | `intent` | 18 | `\b(?:заказать|закажу|готов оплатить|готовы оплатить)\b.{0,80}\b(?:сайт|лендинг|бот|интеграцию|автоматизацию|парсер|интернет[- ]?магазин)\b` | `intent_direct_purchase` |
| `POS-DIR-005` | 304 | `direct_order` | `intent` | 14 | `\b(?:нужно|надо|хочу|хотим|требуется)\b.{0,80}\b(?:снять|отснять|сфотографировать|фотосесси(?:я|ю)|сделать фото)\b` | `intent_direct_photo` |
| `POS-CTR-001` | 320 | `contractor_search` | `intent` | 14 | `\b(?:ищу|ищем|нужен|нужна|нужны|требуется|требуются)\b.{0,80}\b(?:разработчик(?:а|и|ов)?|программист(?:а|ы|ов)?|фрилансер(?:а|ы|ов)?|специалист(?:а|ы|ов)?|подрядчик(?:а|и|ов)?|исполнитель|команда|агентство)\b` | `intent_contractor_search` |
| `POS-CTR-002` | 321 | `contractor_search` | `intent` | 10 | `\b(?:кто возьмётся|кто может взяться|есть свободный разработчик|есть свободный специалист)\b` | `intent_contractor_available` |
| `POS-REC-001` | 340 | `recommendation_request` | `intent` | 10 | `\b(?:посоветуйте|порекомендуйте|можете посоветовать|можете порекомендовать)\b.{0,100}\b(?:разработчик(?:а)?|программист(?:а)?|специалист(?:а)?|подрядчик(?:а)?|исполнитель|команду|агентство)\b` | `intent_recommend_person` |
| `POS-REC-002` | 341 | `recommendation_request` | `intent` | 8 | `\b(?:у кого есть контакты|дайте контакт|поделитесь контактом|кого можете рекомендовать)\b` | `intent_recommend_contact` |
| `POS-POT-001` | 360 | `potential_need` | `intent` | 6 | `\b(?:можно ли|реально ли|как лучше|как можно|как)\b.{0,100}\b(?:сделать|реализовать|подключить|интегрировать|автоматизировать|перенести|собрать)\b` | `intent_potential_how` |
| `POS-POT-002` | 361 | `potential_need` | `intent` | 5 | `\b(?:есть|возникла|появилась|столкнулся|столкнулись)\b.{0,40}\b(?:проблема|ошибка|сложность|потребность)\b` | `intent_potential_problem` |
| `POS-POT-003` | 362 | `potential_need` | `intent` | 5 | `\b(?:устал|устали)\b.{0,60}\b(?:вручную|руками|копировать|переносить|обрабатывать)\b` | `intent_potential_manual_work` |
```

## A.5 Scoring signals

```text
| Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code |
|---|---:|---|---|---:|---|---|
| `SIG-BUD-001` | 400 | `budget_present` | `budget` | 10 | `\b(?:бюджет|стоимость|оплата)\b\s*(?:[:=—-]\s*)?(?:до\s*|от\s*)?\d[\d\s]*(?:₽|руб(?:лей|ля|\.)?|р\b|usd|eur|\$|€)` | `signal_budget_amount` |
| `SIG-BUD-002` | 401 | `budget_present` | `budget` | 8 | `\b(?:готов|готовы|готова)\s+(?:заплатить|оплатить)\b` | `signal_budget_ready` |
| `SIG-DUE-001` | 410 | `deadline_present` | `deadline` | 5 | `\b(?:срок|дедлайн)\b\s*(?:[:=—-]\s*)?(?:до\s*)?\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?` | `signal_deadline_date` |
| `SIG-DUE-002` | 411 | `deadline_present` | `deadline` | 4 | `\b(?:за|в течение)\s+\d+\s+(?:час(?:а|ов)?|дн(?:я|ей)|недел(?:ю|и|ь)|месяц(?:а|ев)?)\b` | `signal_deadline_period` |
| `SIG-URG-001` | 420 | `urgency_present` | `urgency` | 5 | `\b(?:срочно|очень срочно|как можно быстрее|asap|горит)\b` | `signal_urgency` |
| `SIG-STA-001` | 430 | `ready_to_start` | `readiness` | 5 | `\b(?:готов начать|готовы начать|можем начать|стартуем|начать сразу|приступить сегодня)\b` | `signal_ready_start` |
| `SIG-CON-001` | 440 | `contact_present` | `contactability` | 3 | `(?<![\w@])@[a-z0-9_]{5,32}\b` | `signal_contact_username` |
| `SIG-CON-002` | 441 | `contact_present` | `contactability` | 4 | `\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b` | `signal_contact_email` |
| `SIG-CON-003` | 442 | `contact_present` | `contactability` | 4 | `(?<!\d)(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)` | `signal_contact_phone` |
| `SIG-SPC-001` | 450 | `task_specificity` | `specificity` | 10 | `\b(?:нужно|задача|тз)\b.{0,160}\b(?:для|чтобы|с функцией|который|которая|интеграция с)\b` | `signal_task_detail` |
| `SIG-SPC-002` | 451 | `task_specificity` | `specificity` | 8 | `\b(?:оплата|авторизация|личный кабинет|админ(?:ка|панель)|каталог|корзина|уведомления|выгрузка|синхронизация)\b` | `signal_task_feature` |
```

## A.6 `ru-mvp-4` additions and overrides

Version `ru-mvp-4` copies every v3 rule, adds the rows below and replaces only the `SVC-ECOM-002` pattern with the listed v4 pattern. Historical v1–v3 rows/checksums remain unchanged.

```text
| Rule ID | Priority | Target | Dimension | Weight | Exact pattern | Explanation code |
|---|---:|---|---|---:|---|---|
| `NEG-ADV-016` | 135 | `advertising` | `hard_exclusion` | 0 | `\b(?:предлагаю|оказываю|продаю)\b.{0,80}\b(?:услуг(?:у|и)|разработк(?:у|и)|создани(?:е|я)|настройк(?:у|и))\b.{0,80}\b(?:сайт|лендинг|бот|интеграц|автоматизац|парсер|магазин)\b` | `advertising_provider_offer_v4` |
| `NEG-ADV-017` | 136 | `advertising` | `hard_exclusion` | 0 | `\b(?:мои кейсы|мой кейс|в портфолио|покажу портфолио|беру проекты|открыт(?:а|ы)? к заказам)\b.{0,120}\b(?:сайт|лендинг|бот|интеграц|автоматизац|парсер|маркетплейс)\b` | `advertising_portfolio_v4` |
| `NEG-ADV-018` | 137 | `advertising` | `hard_exclusion` | 0 | `\b(?:курс|обучение|вебинар|интенсив|наставничество)\b.{0,100}\b(?:сайт|бот|автоматизац|маркетплейс|wildberries|ozon)\b` | `advertising_training_v4` |
| `NEG-ADV-019` | 138 | `advertising` | `hard_exclusion` | 0 | `\b(?:возврат(?:ы|ов)?|поставка|отгрузка|остатки|склад|доставка|заказы|поддержка)\b.{0,80}\b(?:wildberries|wb|ozon|маркетплейс)\b` | `advertising_marketplace_operations_v4` |
| `POS-DIR-006` | 305 | `direct_order` | `intent` | 16 | `\b(?:нужен|нужна|нужны|требуется|требуются)\b.{0,80}\b(?:сайт|лендинг|telegram[- ]?бот|телеграм[- ]?бот|чат[- ]?бот|интеграц(?:ия|ию)|api|автоматизац(?:ия|ию)|парсер|интернет[- ]?магазин)\b` | `intent_explicit_service_need_v4` |
| `POS-REC-003` | 342 | `recommendation_request` | `intent` | 10 | `\b(?:посоветуйте|порекомендуйте|кого рекомендуете)\b.{0,100}\b(?:кто|человек|исполнитель|разработчик|специалист|команда)?\b.{0,80}\b(?:сделает|разработает|создаст|доработает|настроит|интегрирует|автоматизирует)?\b` | `intent_recommend_contractor_v4` |
| `SVC-ECOM-002` | 241 | `ecommerce` | `service_fit` | 8 | `(?:\b(?:интеграц(?:ия|ии|ию|ией)|api|автоматизац(?:ия|ии|ию|ией)|бот|парсер|сайт|магазин|выгрузка|синхронизация)\b.{0,80}\b(?:маркетплейс(?:а|е|ы|ов)?|wildberries|wb|ozon|яндекс маркет)\b)|(?:\b(?:маркетплейс(?:а|е|ы|ов)?|wildberries|wb|ozon|яндекс маркет)\b.{0,80}\b(?:интеграц(?:ия|ии|ию|ией)|api|автоматизац(?:ия|ии|ию|ией)|бот|парсер|сайт|магазин|выгрузка|синхронизация)\b)` | `service_marketplace_technical_v4` |
```

## A.7 Seed integrity

Data migration MUST сериализовать catalog в canonical JSON: UTF-8, keys sorted, separators `,` и `:`, без ASCII escaping. SHA-256 сохраняется в `RuleSetVersion.checksum`. Startup пересчитывает checksum и блокирует Detection при несовпадении.

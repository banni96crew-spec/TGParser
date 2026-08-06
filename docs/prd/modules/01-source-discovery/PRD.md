# Модульный PRD 01 — Source Discovery

## 1. Назначение и границы

Модуль формирует контролируемый реестр публичных Telegram-источников. Он принимает ручные ссылки и seed-списки, исследует рекомендации и связи между уже одобренными источниками, выполняет bounded keyword scouting публичных источников, объединяет повторные находки и передаёт Collector только источник, вручную одобренный оператором.

Модуль не получает историю сообщений для monitoring, не запускает live-подписку и не создаёт Lead из scouting-evidence.

## 2. Goals и non-goals

### Goals

- Находить публичные каналы, группы и супергруппы пятью утверждёнными graph-способами и keyword scouting.
- Не допускать мониторинг без явного действия единственного оператора.
- Обеспечить детерминированное объединение повторных кандидатов.
- Ограничить каждый discovery run фиксированным бюджетом.
- Оценивать полезность scouting-находок Source Opportunity Score без загрязнения Lead pipeline.
- Сохранять полную техническую историю смены состояния источника.

### Non-goals

- Автоматическое присоединение к источникам.
- Поиск или обработка непубличных источников.
- Автоматическое одобрение источников или включение monitoring.
- Создание Lead / notification из scouting-evidence.
- Платный search и Telegram Stars.
- Сбор monitoring-сообщений и управление Telegram-сессией.
- AI/LLM-поиск или семантическое расширение seed-запросов.
- Расписание автоматических keyword discovery runs.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Запуск graph discovery | Только вручную оператором |
| Запуск keyword scouting | Только вручную оператором (D-057) |
| Максимальная глубина графа | `2` |
| Максимум новых кандидатов за graph run | `100` |
| Максимум Telegram-resolve операций за graph run | `25` |
| Identity priority | Telegram ID, затем normalized username |
| Начальное состояние находки / promotion | `candidate` |
| Начало monitoring | Только после ручного `approve` и успешной технической проверки |
| Keyword search mode | `free_only`; `allow_paid_stars` запрещён (D-050) |
| Active keyword runs | Не более одного одновременно (D-058) |
| Opportunity score owner | `SRC` (D-054); bands `promising`/`review`/`weak` |
| Evidence excerpt | Максимум `240` Unicode code points (D-056) |
| Поддерживаемые ссылки | `https://t.me/<username>`, `http://t.me/<username>`, `t.me/<username>`, `@<username>`, `<username>` |
| Seed import | UTF-8 CSV, заголовок `source_ref`, максимум `1000` строк |

## 4. Source lifecycle

```text
candidate -> approved -> monitoring
candidate -> rejected
monitoring <-> paused
monitoring -> inaccessible
inaccessible -> monitoring
monitoring/paused/inaccessible -> disabled
rejected -> candidate
```

| Переход | Инициатор | Условие |
|---|---|---|
| `candidate → approved` | Оператор | Нажатие `Approve` |
| `approved → monitoring` | Система | `TelegramGateway.validate_source` успешно подтвердил публичность и доступность |
| `candidate → rejected` | Оператор | Нажатие `Reject` с причиной из фиксированного enum |
| `rejected → candidate` | Оператор | Нажатие `Reconsider` |
| `monitoring → paused` | Оператор | Нажатие `Pause` |
| `paused → monitoring` | Оператор | Нажатие `Resume`, затем успешная техническая проверка |
| `monitoring → inaccessible` | Collector | Подтверждённая постоянная ошибка resolve/access |
| `inaccessible → monitoring` | Reconciliation | Успешная повторная техническая проверка |
| `monitoring/paused/inaccessible → disabled` | Оператор | Нажатие `Disable` |

`disabled` является терминальным состоянием MVP. История источника и ранее собранные данные физически не удаляются этим переходом.

Причины `rejected`: `off_topic`, `low_signal`, `duplicate_manual`, `not_needed`. Для `disabled`: `operator_disabled`.

## 5. Functional requirements

### SRC-001 — Ручное добавление

Система MUST принимать один public username или URL, нормализовать его и создавать discovery run с глубиной `0`.

Нормализация MUST:

1. удалить окружающие пробелы;
2. удалить схему и префикс `t.me/` без учёта регистра;
3. удалить начальный `@`;
4. удалить query string, fragment и завершающий `/`;
5. привести username к lower case;
6. отклонить значение, не соответствующее `^[a-z0-9_]{5,32}$`.

### SRC-002 — Импорт seed-списка

Система MUST принимать UTF-8 CSV с единственным обязательным столбцом `source_ref`, максимум `1000` строк и размером не более `1 MiB`. Пустые строки игнорируются. Каждая валидная строка обрабатывается как ручная находка одного run. Ошибочные строки сохраняются в result report с номером строки и кодом ошибки.

### SRC-003 — Методы discovery

Система MUST поддерживать методы `SourceDiscoveryEvent.method` (D-046):

1. `manual` — ручной public username или URL;
2. `seed_import` — импорт seed-списка;
3. `recommendation` — Telegram recommendations через `TelegramGateway.get_recommendations`;
4. `public_link` — публичные `t.me`-ссылки в сообщениях одобренных источников;
5. `mention` — `@username` в сообщениях одобренных источников;
6. `forward_origin` — origin публичных forwarded messages в одобренных источниках.

### SRC-004 — Контроль глубины

Ручная находка имеет depth `0`. Источник, найденный непосредственно из неё, имеет depth `1`. Источник из depth `1` имеет depth `2`. Находки глубже `2` MUST NOT ставиться на resolve и MUST фиксироваться счётчиком `depth_skipped_total`.

### SRC-005 — Бюджет run

Один run MUST создать не более `100` новых candidate records и выполнить не более `25` resolve операций. После достижения лимита оставшиеся references получают outcome `budget_skipped`; они не переносятся в следующий run автоматически.

Уже существующая запись не расходует лимит кандидатов. Проверка локального identity не расходует лимит resolve.

### SRC-006 — Порядок обхода

Очередь discovery MUST использовать breadth-first ordering: `depth ASC`, затем `discovered_at ASC`, затем normalized reference ASC. Такой порядок обеспечивает воспроизводимый расход бюджета.

### SRC-007 — Техническая проверка

Resolve MUST выполняться только через `TelegramGateway`. Валидным кандидатом является публичный `channel`, `megagroup` или `group`, для которого Gateway вернул Telegram ID, title, source type и public username. Пользователи, боты, private invite links и источники без public username получают outcome `unsupported_source`. Gateway adapter может принять Telethon `supergroup` только как внутреннее отображение в `megagroup`; в domain enum значение `supergroup` отсутствует.

### SRC-008 — Дедупликация кандидатов

После resolve система MUST искать существующий источник сначала по Telegram ID. При отсутствии ID-match выполняется поиск по normalized username. При совпадении обновляется alias/history существующей записи; новый `TelegramSource` не создаётся.

Если username у существующего Telegram ID изменился, старый username сохраняется как alias, новый становится current username.

### SRC-009 — Provenance

Каждая находка MUST сохранять `discovery_run_id`, method, depth, parent_source_id, raw_reference, normalized_reference и `discovered_at`. Для ручного ввода `parent_source_id=NULL`.

### SRC-010 — Ручное одобрение

Система MUST запрещать переход в `approved` без UI-команды оператора. Batch approve отсутствует. Каждое одобрение сохраняет timestamp и snapshot title/username/type.

### SRC-011 — Запуск monitoring

После `approve` система MUST выполнить свежую `validate_source`. Только успешный результат переводит источник в `monitoring` и публикует `SourceMonitoringRequested`. Ошибка оставляет состояние `approved` и показывает точный error code оператору.

### SRC-012 — Reject, reconsider, pause и disable

UI MUST реализовать все ручные переходы lifecycle. Каждая команда идемпотентна: повтор той же команды не создаёт дополнительного события и возвращает текущее состояние.

### SRC-013 — Атомарность

Изменение source state и создание outbox event MUST выполняться одной SQLite-транзакцией.

### SRC-014 — История состояния

Каждый фактический переход MUST создавать immutable `SourceApprovalEvent` с `source_id`, `from_state`, `to_state`, `reason_code`, `created_at` и `trigger` (`operator`, `collector`, `reconciliation`).

### SRC-015 — Повторный run

Повторный run с теми же seeds MUST быть безопасным: существующие sources получают дополнительный provenance record, но не дублируются и не меняют state автоматически.

### SRC-016 — Отчёт run

По завершении run система MUST показать: status, started/finished timestamps, число inputs, resolves, created candidates, merged candidates, invalid references, unsupported sources, budget skips, depth skips и errors.

### SRC-017 — Keyword discovery profile

Система MUST поддерживать `KeywordDiscoveryProfile` с уникальным `name` (`1..80`), состояниями `active|archived` и указателем `current_version`. Clean DB seed MUST создать immutable профиль `ecommerce-development-ru` version `3` с exact catalogs SRC-049. Operator migration допускает только version `6→7`. Редактирование профиля MUST создавать новую version, не изменяя уже сохранённые версии.

### SRC-018 — Версионирование профиля

`KeywordDiscoveryProfileVersion` MUST хранить `post_queries_json` (`1..20`), `directory_queries_json` (`0..10`), `replacement_directory_queries_json` (`0..15`), `required_service_profiles_json`, `additional_exclusions_json`, `source_scope` (`groups|channels|all`). Каждый query после trim + casefold MUST иметь длину `3..128` Unicode code points; дубликаты запрещены внутри и между query lists. После ссылки из любого `DiscoveryRun` version MUST быть immutable (D-055). Run MUST фиксировать `profile_version_id`, активный `rule_set_version_id` и `rule_set_checksum`.

### SRC-019 — Ручной запуск keyword scouting

`StartKeywordDiscoveryRun` MUST приниматься только от UI-команды оператора (D-057). Система MUST отклонить старт, если уже существует active keyword run в `queued|running|retry_wait_flood|cancelling` (D-058), если profile version не active, или если Telegram credentials отсутствуют (`telegram_credentials_missing`). Успешный старт MUST одной транзакцией создать `DiscoveryRun(run_type=keyword_scouting, search_mode=free_only)`, развернуть `DiscoveryRunQuery` rows и `Job(job_type=keyword_discovery)`.

### SRC-020 — Бесплатные методы поиска

Keyword run MUST использовать только Gateway methods: `search_global`, `search_public_sources`, `search_source_messages`, и `search_public_posts` только после `check_public_post_search_quota` с подтверждённой бесплатной квотой (D-051). Paid search и любая передача `allow_paid_stars` запрещены (D-050). При Premium required или необходимости Stars query MUST получить `quota_skipped` без платежа; baseline free search продолжается. Принимаются только публичные `channel|megagroup|group` (D-048).

### SRC-021 — Граница scouting-evidence

`SourceDiscoveryEvidence` MUST NOT создавать `TelegramMessage`, `TelegramEventEnvelope`, `Lead`, `LeadScore`, notification outbox и MUST NOT изменять `CollectorCheckpoint` (D-052). Полный текст сверх excerpt, raw author identity и медиа MUST NOT сохраняться (D-056/D-070); разрешены только SEC-018 `author_key`/`author_kind`.

### SRC-022 — Дедупликация scouting-источников

Identity MUST применяться в порядке: `telegram_id` → существующий `TelegramSource.telegram_id` → current username → `SourceAlias` → normalized username fallback. Один Telegram ID MUST давать один `SourceOpportunitySnapshot` на run и может иметь несколько evidence rows.

### SRC-023 — Linked discussion

Opportunity для `ActiveClientChat v1` MUST создаваться только для публичного `megagroup`. Прямо найденный публичный `megagroup` поступает в deep verification. Найденный `channel` является только ephemeral parent: до Gateway call к нему применяются registry/dismiss/presented suppress ledgers; suppressed parent не вызывает `get_linked_discussion`. Для разрешённого parent система через Gateway ищет связанную discussion group и принимает её только если это публичный `megagroup` с username и её собственная canonical identity не suppressed. Parent-channel не получает evidence/snapshot и не считается presented. Linked discussion получает отдельный opportunity с `linked_parent_telegram_id`; auto-join и автоматическое создание `TelegramSource` запрещены. Provenance method при promotion — `linked_discussion`.

### SRC-024 — Глубокая проверка `ActiveClientChat v1` (D-070)

После seed search система MUST выбрать не более `25` источников для deep verification по предварительному рейтингу (число запросов, seed evidence, directory match, приоритет megagroup/linked discussion, свежесть, tie-break Telegram ID).

До первого provider call run MUST сохранить единый reference instant `T=DiscoveryRun.started_at` в UTC. Deep verification MUST читать публичную историю `megagroup` через Gateway `iter_history` newest→older, классифицируя каждое доступное сообщение pinned DET version. Все resume/restart используют тот же `T`. Exact-phrase `search_source_messages` verification MUST NOT быть единственным механизмом доказательства.

Остановка скана источника при первом из:

1. доказаны все quality-пороги ActiveClientChat v1;
2. достигнута граница сообщения `<T-30d` или история исчерпана;
3. просканировано `1500` сообщений источника (source soft-cap);
4. суммарно по run просканировано `7500` сообщений (run soft-cap);
5. источник окончательно недоступен после утверждённых retries или получен explicit cancel.

Technical scheduling: page-based fair waterfill / round-robin по `HISTORY_PAGE_SIZE` между незавершёнными кандидатами, minimum scanned first, пока не найден один quality source, pool exhausted или run cap `7500`. Слабый источник MUST NOT монополизировать `1500`, пока остаются непроверенные кандидаты. Cursor schema v2 MUST сохранять `T`, continuation, counters, UTC active-date set, human-author set, countable-request identities, request-author set, normalized hashes, `hard_excluded_count`, `unknown_author_message_count`, latest request и stop state.

Замкнутые окна: activity `[T-14d,T]`; demand и hard-excluded `[T-30d,T]`; freshness `[T-7d,T]`. Timestamp `>T` не учитывается. Active UTC date считается по сообщениям activity window.

Quality требует одновременно: ≥`100` уникальных непустых сообщений activity window, ≥`10` active UTC dates, ≥`20` distinct human `author_key`, ≥`3` countable client requests demand window, ≥`3` distinct human request authors и latest countable request в freshness window. Activity messages/dates включают любые уникальные непустые сообщения независимо от `author_kind`; author counters включают только `author_kind=user`. `unknown_author_message_count` = число непустых сообщений с `author_kind=unknown` в `[T-30d,T]` после Telegram message-identity dedupe и затем exact `normalized_hash` repost dedupe; timestamp `>T` и пустой text исключаются.

Countable client request = DET category ∈ `{direct_order, contractor_search, recommendation_request}` + ≥1 service profile ∈ `{websites, telegram_bots, integrations_api, automation_parsers, ecommerce}` + нет hard exclusion + `author_kind=user`. `potential_need` не считается. Для `ecommerce` требуется явный технический заказ; отдельные упоминания WB/Ozon/marketplace/orders/shipping/support недостаточны. Message identity `(telegram_peer_id, telegram_message_id)` применяется первой; exact `normalized_hash` не позволяет одному repost увеличить request count. Fuzzy/semantic dedupe запрещён.

Persist только scouting evidence (не `TelegramMessage`/Lead/outbox/checkpoint). Soft-cap без доказательства ⇒ `truth_status=inconclusive`, не reject. `required_service_profiles` и `additional_exclusions` MUST влиять на eligibility/score с explainable reason codes (SRC-045).

### SRC-025 — Source Opportunity Score ActiveClientChat v1

Система MUST рассчитывать детерминированный score `0–100`, принадлежащий `SRC` (D-054), по компонентам:

- requests: `0/1/2/≥3 → 0/12/24/40`;
- distinct request authors: `0/1/2/≥3 → 0/8/16/25`;
- activity messages: `min(8, floor(8 × activity_message_count / 100))`;
- activity days: `min(6, floor(6 × activity_active_day_count / 10))`;
- activity authors: `min(6, floor(6 × activity_distinct_author_count / 20))`;
- recency from `T`: `0..3d→15`, `(3d..7d]→10`, `(7d..30d]→5`, `>30d`/none→0;
- noise penalty: `floor(30 × hard_excluded_count / max(1, client_request_count + hard_excluded_count))`, где hard exclusions — уникальные непустые сообщения `[T-30d,T]` после identity dedupe;
- `score = clamp(sum(positive components) − noise, 0, 100)`; ecommerce bonus отсутствует.

Band: `quality` с score ≥`60` → `promising`; `near` с score ≥`35` → `review`; остальные → `weak`. Enums не переименовываются. Sort: truth `quality,near,inconclusive,rejected`, затем score DESC, latest client request DESC NULLS LAST, Telegram ID ASC. Score MUST NOT копироваться в `TelegramSource.quality_score`.

### SRC-026 — Продвижение в кандидаты

`PromoteOpportunityToCandidate` MUST по optimistic version и `review_state` создать `TelegramSource(candidate)` при отсутствии identity match либо связать существующий source без дубля. Method provenance: `keyword_search` или `linked_discussion`. Promotion MUST NOT вызывать `validate_source`, approval, checkpoint, backfill или monitoring (D-049). `DismissOpportunity` MUST помечать snapshot `dismissed` без создания source и MUST записывать durable suppress для будущих keyword scouting runs по identity order SRC-022.

### SRC-027 — Идемпотентность keyword команд

Повтор `StartKeywordDiscoveryRun` при активном keyword run MUST возвращать conflict без второго Job. Повтор `PromoteOpportunityToCandidate` / `DismissOpportunity` с тем же состоянием MUST быть идемпотентным: без второго source и без лишнего transition event. Повторное чтение Telegram page при том же cursor MUST подавляться unique constraints evidence/snapshot.

### SRC-028 — Отмена keyword run

Оператор MUST иметь возможность отменить active keyword run. Команда устанавливает `cancel_requested_at` на Job и переводит run в `cancelling`; worker MUST проверять флаг между сетевыми вызовами и завершать `cancelled`. Terminal `succeeded|partial|failed|cancelled` MUST NOT принимать повторный cancel как новую мутацию состояния.

### SRC-029 — Лимиты keyword run

Один keyword run MUST соблюдать:

- page size global search `50`, максимум `2` страницы на query/scope;
- seed/global/public_posts hits вне demand window `[T-30d,T]` не квалифицируют source; acquisition MAY видеть более старые hits только для seed ranking;
- общий cap `500` уникальных **persisted** evidence rows; сверх лимита — `budget_skipped` (history scan counters `scanned_*` независимы);
- directory search максимум `20` peer results на query;
- deep verification максимум `25` источников; per-source history soft-cap `1500`; whole-run history soft-cap `7500`;
- FloodWait: persist exact cursor/source progress, query `available_at=until`, Job `retry_wait`, run `retry_wait_flood`; worker MUST NOT долго спать в event loop, MUST NOT restart run и MUST NOT retry раньше `until`;
- transient query retry максимум `3` attempts с delays `30`, `120`, `600` секунд.

### SRC-046 — Truth status источника (D-070)

Каждый opportunity после verification MUST получить `truth_status`:

| Status | Условие |
|---|---|
| `quality` | Публичный `megagroup`; все шесть порогов SRC-024 доказаны |
| `near` | Завершённый 30-дневный scan/exhaustion, ≥1 countable request, но любой quality-порог не выполнен |
| `inconclusive` | Terminal incomplete scan из-за source/run cap, окончательной недоступности или explicit cancel |
| `rejected` | Завершённый 30-дневный scan/exhaustion, `0` countable requests |

Closed `verification_stop_reason`: `quality_reached|window_complete|history_exhausted|source_cap|run_cap|inaccessible|cancelled`. Ordered qualification reasons: `quality_pass`, `activity_messages_below_100`, `activity_days_below_10`, `activity_authors_below_20`, `client_requests_below_3`, `client_authors_below_3`, `latest_request_older_than_7d`, `source_cap_incomplete`, `run_cap_incomplete`, `inaccessible_incomplete`, `cancelled_incomplete`. `inconclusive` отображается как «недоказанный»; incomplete path не маппится в `near`/`rejected`.

### SRC-047 — Working-run gate (D-070)

Keyword run MUST вычислять `gate_status`:

1. `pass`, если `quality_sources ≥ 1`, независимо от остальных результатов;
2. `inconclusive`, если PASS нет и run достиг `7500`, лимита `25` deep-verification sources или иного acquisition budget до доказанного provider exhaustion, потерял оставшиеся free queries из-за quota, отменён, завершился `partial|failed`, имеет необработанные candidates либо хотя бы один terminal source `inconclusive` из-за source cap/inaccessible/cancel;
3. `fail` только если PASS нет, acquisition pool действительно exhausted, все acquired candidates получили terminal `near|rejected`, необработанных/inconclusive candidates нет;
4. active `queued|running|retry_wait_flood|cancelling` run хранит provisional `gate_status=inconclusive`, который не является release evidence.

Counters MUST включать `quality_sources`, `near_sources`, `inconclusive_sources`, `rejected_sources`, `countable_client_requests`, `distinct_client_authors`, `history_scanned_total`, `gate_status`, `hit_run_cap`, `pool_exhausted`.

### SRC-048 — FloodWait/crash resume для history verification (D-070)

На любом history/provider call FloodWait MUST сохранить cursor v2, перевести run в `retry_wait_flood` до exact `until`, затем продолжить тот же run/source с прежним `T`. FloodWait и process crash не создают terminal truth, terminal metrics, presented result или suppress membership. Atomic page commit и resume MUST исключать duplicate counters/evidence. Crash recovery продолжает тот же cursor; новый run не создаётся.

### SRC-049 — Immutable acquisition profile v3/v7 (D-070)

Clean DB seed `ecommerce-development-ru` MUST быть immutable version `3`. Для operator upgrade migration разрешена только observed current version `6` → immutable version `7`; другое значение блокирует activation. Post queries version 3/7 ровно: `нужен сайт`, `ищу разработчика сайта`, `кто сделает сайт`, `нужен лендинг`, `нужен telegram бот`, `разработать telegram бота`, `нужен бот для заказов`, `нужна интеграция api`, `интеграция сайта crm`, `интеграция с 1с`, `нужен парсер`, `автоматизировать заказы`, `нужна автоматизация`, `нужен интернет-магазин`, `доработать интернет-магазин`, `интеграция ozon`, `интеграция wildberries`, `нужен магазин на сайте`.

Primary directory queries ровно: `чат предпринимателей`, `сообщество предпринимателей`, `владельцы бизнеса`, `основатели стартапов`, `владельцы интернет-магазинов`, `чат селлеров`, `рестораторы чат`, `владельцы салонов чат`, `онлайн-школы чат`, `малый бизнес чат`.

Replacement queries ровно: `предприниматели москва`, `предприниматели спб`, `предприниматели казань`, `предприниматели екатеринбург`, `предприниматели краснодар`, `малый бизнес сообщество`, `владельцы кафе чат`, `владельцы ресторанов чат`, `владельцы салонов красоты чат`, `онлайн школы сообщество`, `частные клиники чат`, `турбизнес чат`, `риелторы предприниматели чат`, `производители чат`, `локальный бизнес чат`. Runtime-generated variants/grammar запрещены. Directory candidates с provider/developer/service-offer tokens отбрасываются до deep quota с explainable reason. Public posts Premium/Stars outcomes различаются; `allow_paid_stars=None` неизменен.

### SRC-030 — Retention keyword artifacts

Ежедневный purge MUST применять:

| Данные | Срок |
|---|---:|
| `SourceDiscoveryEvidence.excerpt` | 30 дней |
| Evidence rows без текста | 90 дней |
| Unpromoted opportunity snapshots | 90 дней |
| Keyword `DiscoveryRunQuery` rows | 90 дней |
| Terminal keyword runs | 90 дней |
| Profile versions | без автоматического удаления |
| Promoted `SourceDiscoveryEvent` | существующая source provenance policy |

Batch максимум `500` rows за транзакцию. После очистки evidence UI MUST показывать «Доказательства очищены по retention policy», а не пустую ошибку.

### SRC-031 — Cross-run suppress registry sources (D-059)

Keyword scouting MUST suppress источники, уже присутствующие в Source Registry:

- match по identity order SRC-022 (`telegram_id` → registry `telegram_id` → username → alias);
- любой `lifecycle_state` реестра считается известным;
- suppressed `telegram_id` MUST NOT получать `SourceDiscoveryEvidence` и `SourceOpportunitySnapshot` в текущем run;
- suppressed `telegram_id` MUST NOT входить в deep-verification selection (≤25) и MUST NOT порождать linked-discussion opportunity;
- seed/directory/public_posts search MAY всё ещё получать hits от Telegram;
- run counter `registry_suppressed` MUST равняться числу **уникальных** suppressed `telegram_id` за run;
- SRC-022 внутри run сохраняется: один snapshot на новый (не suppressed) Telegram ID;
- dismissed suppress из SRC-032 применяется отдельно от registry suppress и использует тот же identity order.

### SRC-032 — Global dismiss suppress for future runs (D-060)

`DismissOpportunity` MUST создавать durable suppress-правило для будущих keyword scouting runs:

- match по identity order SRC-022 (`telegram_id` → registry `telegram_id` → username → alias);
- suppressed dismissed source MUST NOT получать `SourceDiscoveryEvidence` и `SourceOpportunitySnapshot` в любом следующем keyword run;
- suppressed dismissed source MUST NOT входить в deep-verification selection (≤25) и MUST NOT порождать linked-discussion opportunity;
- suppress MUST переживать retention `SourceOpportunitySnapshot` и MUST NOT зависеть только от `review_state` старого snapshot;
- повторный dismiss того же suppressed источника MUST оставаться идемпотентным;
- run counter `dismissed_suppressed` MUST равняться числу **уникальных** suppressed `telegram_id` за run.

### SRC-033 — Canonical source identity model

Система MUST представлять публичный источник через logical `CanonicalSourceIdentity` (D-061):

- `canonical_key` ∈ {`peer:<telegram_id>`, `username:<casefold>`};
- after resolve, canonical identity is Telegram numeric peer ID;
- linked `SourceAlias[]` remain owned by SRC (no dual owner);
- identity match order (frozen): `telegram_id` → registry `telegram_id` → current username → `SourceAlias` → provisional `username:<casefold>`;
- one canonical key per opportunity snapshot per run (extends SRC-022);
- promotion/suppress match MUST use `canonical_key`.

### SRC-034 — Provisional identity lifecycle and atomic merge

Unresolved username opportunities MUST use provisional key `username:<casefold>` until resolve (D-061):

- provisional identity MUST NOT reach `lifecycle_state=monitoring`;
- after resolve, transactional merge into `peer:<telegram_id>` MUST preserve dismiss provenance and aliases;
- merge emits existing `SourceApprovalEvent` / discovery merge outcomes — no second event owner.

### SRC-035 — Dismiss suppress ledger entity

Durable suppress ledger `DismissedSource` / `DismissedKeywordSource` MUST store (D-062 / SRC-032):

- `canonical_key`, nullable `telegram_id`, usernames/aliases JSON, `dismiss_reason`, `dismissed_at`, nullable `source_opportunity_id`, `operator_trigger`, version/upsert stamp;
- membership is permanent until explicit `ReconsiderDismissSuppress`;
- claim fields MAY upsert;
- the sole authoritative audit event for successful reconsider is `DismissSuppressReconsidered` (owner `SRC`); `SourceDiscoveryEvent` MUST NOT be used as an alternate or second authoritative reconsider channel;
- snapshot `review_state=dismissed` alone is NOT durable suppress.

### SRC-036 — ReconsiderDismissSuppress command

`ReconsiderDismissSuppress(canonical_key|suppress_id, note, CSRF, version)` MUST remove suppress membership only via that explicit action and MUST emit authoritative audit event `DismissSuppressReconsidered` (D-062 / SRC-035). It is distinct from `ReconsiderSource` (`rejected→candidate`). Re-dismiss remains idempotent (SRC-032).

### SRC-037 — Discovery run funnel counters and novelty

Completed keyword `DiscoveryRun` MUST persist funnel counters (D-063 / D-069): `acquired_total`, `canonicalized_total`, `registry_suppressed`, `dismissed_suppressed`, `duplicate_in_run`, `presented_suppressed` (unique already-shown peers; `cooldown_suppressed` is a historical alias of the same unique count), `qualified_total`, `presented_total`, `novel_presented_total`, `replacement_fetches_total`; `novelty_ratio = novel_presented_total / max(1, presented_total)`. Deterministic fixture with sufficient replacement pool: `novelty_ratio ≥ 0.80` after first run; dismissed recurrence across future runs = `0`. Live pilot: `5` sequential runs; median pairwise Jaccard of presented canonical sets ≤ `0.60` OR each violating run has proven `pool_exhausted=true` with reason.

### SRC-038 — pool_exhausted terminal reason codes

Only proven exhaustion of all allowed free replacement paths sets `pool_exhausted=true`, with closed reason `provider_empty|no_unseen_after_suppress`. Reaching deep cap `25`, history run cap `7500`, another bounded acquisition budget or `quota_skipped_remaining` while provider paths may remain sets `pool_exhausted=false`, `gate_status=inconclusive` and `run_termination_reason=deep_candidate_cap|history_run_cap|acquisition_budget_cap|quota_skipped_remaining`. `FloodWait` is resumable and sets neither exhaustion nor terminal reason. Explicit cancel uses `run_termination_reason=cancelled` plus SRC-046 inconclusive outcomes and MUST NOT set pool exhaustion.

### SRC-039 — Acquisition / qualification / presentation stages

Keyword worker MUST separate stages (D-063): `acquired` → `canonicalized` → `suppressed` → `qualified` → `presented`. Provenance MUST record provider method ∈ existing discovery methods + `keyword_search`/`linked_discussion`/`recommendation`/`public_link`/`mention`/`forward_origin`. Profile fields `required_service_profiles` and `additional_exclusions` apply under this stage model with SRC-024 caps.

### SRC-040 — Replacement acquisition after suppress

After registry/dismiss/presented suppress, worker MUST continue free provider cursor/replacement fetches (directory expansion queries, remaining pages, linked discussion/recommendations where already contracted) until deep-verification quota OR truthful `pool_exhausted` (D-063 / D-069). Permanent dismiss (SRC-032) and durable presented suppress (SRC-041) are not temporary cooldowns. Stars/paid paths MUST NOT be used. `pool_exhausted=no_unseen_after_suppress` ONLY after all allowed free replacement paths for the run are exhausted.

### SRC-041 — Durable presented-source suppress (D-069; supersedes 24h cooldown)

Already-presented canonical identity from any prior keyword opportunity snapshot (any `truth_status`, including quality/near/inconclusive/rejected) MUST be durably suppressed from future keyword scouting runs:

- suppressed peer MUST NOT receive new `SourceDiscoveryEvidence` / `SourceOpportunitySnapshot` / deep-verification selection / linked-discussion opportunity in later keyword runs;
- suppress MUST use SRC-022 identity order (peer id after resolve; username aliases MUST NOT bypass);
- suppress MUST persist across restart and MUST survive `SourceOpportunitySnapshot` retention (STO-020);
- distinct from registry suppress (SRC-031) and permanent dismiss (SRC-032);
- upsert on first presentation is idempotent; historical snapshots MUST be backfilled into the ledger;
- run counter `presented_suppressed` MUST equal the number of **unique** canonical peers suppressed as already-shown in the run; funnel field `cooldown_suppressed` is a historical alias of that same unique count (no double-count).

The prior «24 hours then show again» rule is **void** (D-069).

### SRC-050 — Presented suppress ledger entity

Durable ledger `PresentedKeywordSource` MUST store (D-069 / SRC-041):

- `canonical_key`, nullable `telegram_id`, usernames/aliases JSON, `first_presented_at`, nullable `origin_run_id` / `origin_opportunity_id`, version/upsert stamp;
- uniqueness on `canonical_key` and on `source_telegram_id` when set;
- physical table + retention immunity owned by STO (STO-020);
- snapshot presence alone after retention is NOT sufficient — ledger membership is authoritative.

### SRC-042 — Graph edge types and public-only targets

Graph discovery MUST allow only closed public-only edge types: `recommendation`, `public_link`, `mention`, `forward_origin`, `linked_discussion` (SRC-003/023). Targets MUST be public `channel|megagroup|group` with resolvable public identity. Private/invite-only/unconfirmed username MUST NOT become candidates (`unsupported_source` / skip). Limits remain D-017 / SRC-004/005: `max_depth=2` (supersedes any plan prose `depth=1`), `candidate_cap=100`, `resolve/expansion_cap=25`, max outgoing edges examined per seed node = `25`, max unique graph candidates/run = `100`, one canonical node resolved at most once per run. FloodWait → provider phase `retry_wait` / run degraded with state preserved.

### SRC-043 — Evidence eligibility gates

Directory-only opportunities (no message/member/activity evidence) MUST NOT receive band `review` or `promising`; score forced into `weak` `0–34` with reason `directory_only_no_evidence`. Linked discussion / source lacking verification evidence → reason `needs_verification`; MUST NOT get `review`/`promising` (plan `moderate`/`strong` aliases) without deep verification.

### SRC-044 — Neutral noise sampling

Deep verification MUST classify all fetched unique non-empty messages, not only query hits. UI evidence sample сохраняет не более `20` neutral/hard-excluded excerpts from `[T-30d,T]`; cursor/snapshot сохраняют полный `hard_excluded_count` after dedupe для SRC-025. Те же caps и frozen `T`, что SRC-024.

### SRC-045 — Profile semantics enforcement

`required_service_profiles` MUST affect eligibility/score; `additional_exclusions` MUST apply with explainable reason codes. Profile semantics are owned by SRC opportunity path, not SCR.

## 6. Входные и выходные контракты

### Команды

| Команда | Обязательные поля | Результат |
|---|---|---|
| `StartDiscoveryRun` | `method`, `source_refs[]` или `parent_source_id` | `discovery_run_id` |
| `CreateKeywordDiscoveryProfile` | `name`, queries, scope | `profile_id` |
| `CreateKeywordDiscoveryProfileVersion` | `profile_id`, queries, scope, `version` | новая version |
| `StartKeywordDiscoveryRun` | `profile_id` | `discovery_run_id` |
| `CancelKeywordDiscoveryRun` | `run_id`, `version` | `cancelling`/`cancelled` |
| `PromoteOpportunityToCandidate` | `opportunity_id`, `version` | candidate source id |
| `DismissOpportunity` | `opportunity_id`, `reason`, `version` | `dismissed` + future keyword suppress |
| `ReconsiderDismissSuppress` | `canonical_key` \| `suppress_id`, `note`, `version` | suppress membership removed |
| `ApproveSource` | `source_id` | новое состояние или validation error |
| `RejectSource` | `source_id`, `reason_code` | `rejected` |
| `ReconsiderSource` | `source_id` | `candidate` |
| `PauseSource` | `source_id` | `paused` |
| `ResumeSource` | `source_id` | `monitoring` или validation error |
| `DisableSource` | `source_id` | `disabled` |

### События

| Событие | Обязательные поля |
|---|---|
| `SourceCandidateDiscovered` | `event_id`, `source_id`, `run_id`, `method`, `occurred_at` |
| `KeywordDiscoveryRunStarted` | `event_id`, `run_id`, `profile_version_id`, `rule_set_version_id`, `occurred_at` |
| `KeywordDiscoveryRunFinished` | `event_id`, `run_id`, `state`, funnel counters, `pool_exhausted`, `pool_exhausted_reason`, `novelty_ratio`, `occurred_at` |
| `SourceOpportunityPromoted` | `event_id`, `opportunity_id`, `source_id`, `method`, `occurred_at` |
| `DismissSuppressReconsidered` | `event_id`, `canonical_key` \| `suppress_id`, `note`, `occurred_at` |
| `SourceMonitoringRequested` | `event_id`, `source_id`, `telegram_id`, `occurred_at` |
| `SourcePaused` | `event_id`, `source_id`, `occurred_at` |
| `SourceDisabled` | `event_id`, `source_id`, `occurred_at` |

Все события получают UUIDv7 `event_id` и записываются в transactional outbox, где применимо для lifecycle transitions.

## 7. Data ownership

Модуль владеет сущностями `TelegramSource`, `DiscoveryRun`, `DiscoveryRunQuery`, `SourceDiscoveryEvent`, `SourceAlias`, `SourceApprovalEvent`, `KeywordDiscoveryProfile`, `KeywordDiscoveryProfileVersion`, `SourceDiscoveryEvidence`, `SourceOpportunitySnapshot`, logical `CanonicalSourceIdentity`, `DismissedSource` / `DismissedKeywordSource` и logical `PresentedKeywordSource`. Candidate является `TelegramSource` в состоянии `candidate`, отдельной candidate table нет. Collector владеет checkpoints и collection jobs, но не source state machine. Physical suppress tables and retention immunity are STO (STO-017, STO-020).

Ключевые ограничения:

- `TelegramSource.telegram_id` — unique, nullable только до первого resolve / provisional;
- provisional identity MUST NOT enter `monitoring` (D-061 / SRC-034);
- `SourceAlias.normalized_username` — unique;
- не более одного active `graph` DiscoveryRun одновременно;
- не более одного active `keyword_scouting` DiscoveryRun одновременно (D-058);
- opportunity score не копируется в `quality_score` (D-054);
- timestamps сохраняются в UTC с точностью до миллисекунд.

## 8. Ошибки, retry и recovery

- `FloodWait` передаётся Gateway и выдерживается полностью; discovery job переходит в `retry_wait`, а run остаётся `running` (graph) или `retry_wait_flood` (keyword) и затем продолжается с сохранённого cursor/queue item.
- Сетевые ошибки graph discovery получают до `5` попыток через `1`, `5`, `30`, `120`, `600` секунд.
- Keyword query transient errors: максимум `3` attempts через `30`, `120`, `600` секунд; ошибка одной query обычно даёт run `partial`.
- `USERNAME_NOT_OCCUPIED`, invalid username и unsupported entity не повторяются.
- Unauthorized/frozen session переводит keyword run в `failed`.
- Crash recovery продолжает run с первого queue item / сохранённого cursor без terminal outcome.
- После исчерпания retry item/query получает `failed`, а run продолжает остальные items.

## 9. Security requirements

- Source references и CSV не интерпретируются как HTML или shell input.
- CSV formula prefixes `=`, `+`, `-`, `@` экранируются апострофом только при формировании result export.
- Модуль не читает Telegram session-файл напрямую.
- В логах сохраняются source ID, run ID, query ordinal, method, result count, error code и duration; полный текст сообщений, excerpts и authors в логах отсутствуют.

## 10. Observability

Метрики:

- `discovery_runs_total{status,method}`;
- `discovery_candidates_total{outcome,method,depth}`;
- `discovery_resolves_total{outcome}`;
- `discovery_run_duration_seconds`;
- `source_state_transitions_total{from,to,trigger}`;
- `discovery_budget_skipped_total{kind}`;
- `discovery_runs_total{state}` (keyword);
- `discovery_queries_total{kind,outcome}`;
- `discovery_search_hits_total{kind}`;
- `discovery_unique_sources_total`;
- `discovery_verified_sources_total`;
- `discovery_qualified_evidence_total`;
- `discovery_promotions_total{result}`;
- `discovery_flood_wait_seconds`;
- `discovery_quota_skipped_total`;
- `discovery_score_total{band}`.

Запрещённые metric labels: query text, source title, username, run ID, Telegram ID.

Structured log MUST включать `run_id`, `source_id`, `method`, `depth`, `outcome`, `duration_ms`, `error_code` без session credentials, excerpts и authors.

## 11. Dependencies

- `02-telegram-collector`: получает только `SourceMonitoringRequested`.
- `06-lead-storage`: транзакции, repositories и outbox.
- `07-lead-dashboard`: candidate review и ручные команды.
- `09-operator-settings`: фиксированные настройки отображения discovery.
- `10-administration-observability`: metrics, logs и run status.
- `11-security`: secrets boundary и log redaction.

## 12. MVP и исключённые функции

MVP включает SRC-001—SRC-050 полностью. Исключены semantic topic search, fuzzy source matching, автоматическое approval, batch approval, глубина выше `2`, платный search/Stars, создание Lead из evidence и расписание автоматических discovery runs.

## 13. Acceptance criteria и test catalogue

| ID | Требование | Сценарий | Ожидаемый результат |
|---|---|---|---|
| `AT-SRC-001` | SRC-001 | Ввести `https://t.me/Test_Channel/?x=1` | Получен `test_channel`; создаётся один run |
| `AT-SRC-002` | SRC-002 | Импортировать CSV с валидными, пустыми и ошибочными строками | Валидные обработаны; ошибки содержат номера строк |
| `AT-SRC-003` | SRC-003 | Запустить каждый из пяти методов | Provenance содержит точный method |
| `AT-SRC-004` | SRC-004 | Найти ссылку с depth `3` | Resolve не вызван; depth skip увеличен |
| `AT-SRC-005` | SRC-005 | Подать 150 уникальных валидных references | Создано не более 100 candidates и выполнено не более 25 resolves |
| `AT-SRC-006` | SRC-006 | Повторить run на одинаковом fixture | Порядок outcome идентичен |
| `AT-SRC-007` | SRC-007 | Resolve пользователя, private link и public channel | Candidate создаётся только для public channel |
| `AT-SRC-008` | SRC-008 | Найти один Telegram ID под старым и новым username | Один source, два aliases, новый current username |
| `AT-SRC-009` | SRC-009 | Найти источник через mention | Сохранены parent, method и depth |
| `AT-SRC-010` | SRC-010 | Завершить discovery без действий оператора | Все находки остаются `candidate` |
| `AT-SRC-011` | SRC-011 | Approve при успешной и ошибочной validation | Monitoring/event только при успехе |
| `AT-SRC-012` | SRC-012 | Дважды выполнить Pause | Состояние paused; один transition event |
| `AT-SRC-013` | SRC-013 | Инъецировать сбой outbox insert | State transition полностью откатан |
| `AT-SRC-014` | SRC-014 | Выполнить все допустимые переходы | История точна и immutable |
| `AT-SRC-015` | SRC-015 | Дважды запустить одинаковые seeds | Source не дублируется и state не меняется |
| `AT-SRC-016` | SRC-016 | Завершить mixed-outcome run | Все счётчики равны fixture |
| `AT-SRC-017` | SRC-017 | Создать clean DB seed `ecommerce-development-ru` | Profile active; immutable version `3` с exact SRC-049 catalogs |
| `AT-SRC-018` | SRC-018 | Изменить любую primary/replacement query после run | Создана следующая version; referenced version неизменна; cross-list duplicate отклонён |
| `AT-SRC-019` | SRC-019 | Запустить keyword run вручную при отсутствии active run | Созданы run+queries+Job; UI redirect на run |
| `AT-SRC-020` | SRC-020 | Free quota есть / Stars required / Premium required | Free search выполнен; paid/Premium → `quota_skipped`; `allow_paid_stars is None` |
| `AT-SRC-021` | SRC-021 | Завершить keyword run с hits | Нет `TelegramMessage`/Lead/outbox/checkpoint изменений |
| `AT-SRC-022` | SRC-022 | Один Telegram ID найден двумя queries | Один snapshot; ≥2 evidence rows |
| `AT-SRC-023` | SRC-023 | Direct megagroup; unseen/suppressed channel parents; linked group wrong type/suppressed/valid | Verification получает только unsuppressed public megagroup; parent не получает snapshot; join не вызван |
| `AT-SRC-024` | SRC-024 | Fixed-clock history crosses 7/14/30d, all 100/10/20/3/3 boundaries, unknown-author replay and caps | Counters use immutable T; unknown counts nonempty 30d after identity+hash dedupe; all thresholds required; caps incomplete→inconclusive |
| `AT-SRC-025` | SRC-025 | Boundary fixtures for every component, recency range and noise | Exact integer score/band/sort match; ecommerce has no bonus; `quality_score` source unchanged |
| `AT-SRC-026` | SRC-026 | Promote нового и существующего snapshot | Candidate создан один раз / linked; monitoring не стартовал |
| `AT-SRC-027` | SRC-027 | Повтор start при active run и повтор promote | Conflict / идемпотентный promote без дубля |
| `AT-SRC-028` | SRC-028 | Cancel во время running | `cancelling`→`cancelled`; сетевые вызовы прекращены после текущей page |
| `AT-SRC-029` | SRC-029 | Превысить evidence cap и получить FloodWait | `budget_skipped`; run `retry_wait_flood` до `until` |
| `AT-SRC-030` | SRC-030 | Evidence старше 30/90 дней | Excerpt/rows/snapshots/runs очищены по матрице |
| `AT-SRC-031` | SRC-031 | Registry содержит `telegram_id=X` (любой lifecycle); run находит hits для `X` и нового `Y` | Нет evidence/opportunity/deep query для `X`; opportunity только для `Y`; `registry_suppressed` ≥ 1 |
| `AT-SRC-032` | SRC-032 | В run-1 оператор dismiss-ит opportunity для `telegram_id=X`; run-2 снова находит hits для `X` и нового `Y` | В run-2 нет evidence/opportunity/deep query/linked discussion для `X`; opportunity только для `Y`; `dismissed_suppressed` ≥ 1 |
| `AT-SRC-033` | SRC-033 | Same peer under two usernames | One identity, two aliases |
| `AT-SRC-034` | SRC-034 | Unresolved username opportunity → provisional key; after resolve merge into peer | Dismiss provenance retained; monitoring blocked while provisional |
| `AT-SRC-035` | SRC-035 | Dismiss creates suppress row; purge snapshots | Suppress membership remains; recurrence = 0 |
| `AT-SRC-036` | SRC-036 | `ReconsiderDismissSuppress` then new run finds same peer | Opportunity may appear again; exactly one authoritative `DismissSuppressReconsidered`; distinct from `ReconsiderSource` |
| `AT-SRC-037` | SRC-037 | Fixture with sufficient replacement pool after first run | `novelty_ratio ≥ 0.80`; dismissed recurrence = 0 |
| `AT-SRC-038` | SRC-038 | Exhaust provider after suppress without quota fill | `pool_exhausted=true` with closed reason code |
| `AT-SRC-039` | SRC-039 | Trace single hit through stages | Stages `acquired→…→presented` recorded with provenance method |
| `AT-SRC-040` | SRC-040 | Suppress removes presented slot; initial provider results mostly seen | Replacement/expansion fetches raise `replacement_fetches_total`; later unseen sources verified; `pool_exhausted` only after free paths exhausted |
| `AT-SRC-041` | SRC-041 | Present quality/near/rejected peer; next run finds same peer | No evidence/snapshot/deep for peer; `presented_suppressed` ≥ 1; survives restart + snapshot retention; alias/canonical merge does not bypass |
| `AT-SRC-042` | SRC-042 | Private invite and depth-3 public link | Private skipped; depth>2 not resolved; depth stays `2`, caps `100`/`25` |
| `AT-SRC-043` | SRC-043 | Directory-only peer without message evidence | Band `weak`, reason `directory_only_no_evidence` |
| `AT-SRC-044` | SRC-044 | Deep sample includes query/non-query/hard-excluded duplicates | All unique messages classified; ≤20 samples; exact 30d hard-excluded count persisted |
| `AT-SRC-045` | SRC-045 | Profile with `required_service_profiles` + exclusion | Eligibility/score reflect profile; exclusion reason explainable |
| `AT-SRC-046` | SRC-046 | Complete/incomplete scans over full threshold matrix | Exact quality/near/inconclusive/rejected and ordered closed reasons |
| `AT-SRC-047` | SRC-047 | Zero/one quality plus provider exhaustion, deep cap 25, acquisition/history caps, quota, cancel, failed and source-inconclusive paths | Complete ordered table gives exact pass/fail/inconclusive; any stop before proven pool exhaustion is inconclusive |
| `AT-SRC-048` | SRC-048 | FloodWait/process restart crosses time boundaries | Same T/cursor/source; byte-equivalent outcome; no pre-terminal metric/presentation/suppress |
| `AT-SRC-049` | SRC-049 | Clean seed; operator 6→7; wrong version; exact query catalogs | v3/v7 exact and immutable; wrong operator version blocks; no generated variants; Stars=0 |
| `AT-SRC-050` | SRC-050 | Presentation creates ledger row; purge snapshots | Presented suppress membership remains; registry/dismiss/presented reasons distinguishable |

## 14. Принятые записи decision log

- `DEC-SRC-001`: discovery запускается только вручную.
- `DEC-SRC-002`: graph depth равен `2`, candidate cap равен `100`, resolve cap равен `25`.
- `DEC-SRC-003`: любая находка сначала получает `candidate` и требует одиночного ручного approval.
- `DEC-SRC-004`: identity определяется Telegram ID, затем normalized username.
- `DEC-SRC-005`: private-source auto-join отсутствует.
- `D-048`–`D-058`: keyword scouting contract freeze (public-only, promote-only source creation, Zero Stars, free `searchPosts`, evidence isolation, linked discussion, SRC opportunity score, versioned profile/formula, excerpt ≤240, manual launch, single active keyword run).
- `D-059`: cross-run suppress registry-known sources (SRC-031).
- `D-060`: dismissed keyword result becomes durable future-run suppress (SRC-032).
- `D-061`: provisional identity + peer merge (SRC-033/034).
- `D-062`: suppress ledger + `ReconsiderDismissSuppress` (SRC-035/036).
- `D-063`: acquisition≠qualification, novelty, pool_exhausted (SRC-037..041).
- `D-070`: ActiveClientChat v1 supersedes D-068 qualification/score/truth/run gate; frozen time, human authors, deterministic resume and live owner evidence (SRC-023..025, SRC-044, SRC-046..049).
- `D-069`: durable presented-source suppress supersedes 24h cooldown; free replacement acquisition after mass suppress (SRC-041/050, SRC-040).
- `D-067`: opportunity bands stay `promising|review|weak`; plan `strong|moderate` aliases only.

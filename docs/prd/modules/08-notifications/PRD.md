# PRD модуля 08 — Notifications

## 1. Назначение и границы

Модуль доставляет одному оператору минимальные Telegram notifications для новых hot leads и критических runtime incidents. Доставка выполняется через transactional outbox и Telegram Bot API. Модуль не читает Telegram sources, не рассчитывает score и не отправляет сообщения авторам лидов.

## 2. Goals

- уведомлять о новом hot lead не позднее 30 секунд p95 после commit Lead;
- не отправлять warm/cold/irrelevant leads;
- переживать restart без потери outbox events;
- исключать повторную автоматическую отправку одного business event;
- показывать delivery state и ошибки в локальном Dashboard;
- доставлять только короткий и понятный excerpt.

## 3. Non-goals

- automatic outreach и ответы авторам;
- email, SMS, push и несколько Telegram recipients;
- quiet hours и digest;
- full message text или вложения;
- изменение lead status из notification;
- correction message при снижении score.

## 4. Принятый стек и конфигурация

- direct Telegram Bot API;
- один shared `httpx.AsyncClient`;
- bot token читается только из environment variable `TLD_TELEGRAM_BOT_TOKEN`;
- destination chat ID хранится в SQLite setting `notification.telegram_chat_id`;
- recipient ровно один;
- quiet hours отключены;
- worker poll interval — 1 секунда;
- HTTP timeouts: connect 5 секунд, read 10 секунд, write 10 секунд, pool 5 секунд.

Перед operational readiness выполняются `getMe` и ручная test notification. Успех сохраняется как health state. Отсутствующие/неверные credentials делают Notifications unhealthy, но не останавливают Collector и Dashboard.

## 5. Notification eligibility

### 5.1. Lead events

Notification создаётся только если:

1. первый score Lead имеет band `hot`; или
2. текущий band Lead изменился с `warm`, `cold` или `irrelevant` на `hot`.

Notification не создаётся:

- для warm, cold и irrelevant;
- при re-score `hot → hot`;
- при снижении `hot → warm/cold/irrelevant`;
- для duplicate non-canonical message;
- при replay уже обработанного scoring event.

Повторный переход того же Lead из non-hot в hot создаёт новый event с новой `score_version`.

### 5.2. System events

Отправляются только три типа критических incidents:

- `collector_stopped`;
- `telegram_session_unavailable`;
- `database_startup_failed` для migration или integrity check error.

Один incident создаёт один outbox event. Повторяющиеся health probes не создают новые events, пока component не вернётся в healthy state. Новый отказ после recovery получает новый `incident_id`.

## 6. Idempotency

Lead event key:

```text
{event_type}:{lead_id}:{score_version}
```

System event key:

```text
{event_type}:{incident_id}
```

- key имеет unique constraint в `notification_outbox`;
- `score_version` является монотонной версией immutable LeadScore внутри Lead;
- outbox row создаётся в той же transaction, что и текущий LeadScore;
- replay одного scoring event возвращает существующий outbox ID;
- один outbox event может иметь несколько delivery attempts, но только один `sent` result.

## 7. Состав lead notification

Порядок полей фиксирован:

1. `🔥 Горячий лид · {score}/100`;
2. русская label category;
3. source title;
4. published time в `Europe/Moscow`;
5. excerpt;
6. source permalink, если он сохранён и валиден;
7. internal lead ID.

Category labels:

| Category | Label |
|---|---|
| `direct_order` | Прямой заказ |
| `contractor_search` | Поиск исполнителя |
| `recommendation_request` | Запрос рекомендации |
| `potential_need` | Потенциальная потребность |

Excerpt:

- берётся из canonical current message text;
- последовательности whitespace заменяются одним пробелом;
- длина ограничена первыми 500 Unicode code points;
- после truncation добавляется `…`;
- HTML escaping выполняется после truncation.

Не включаются полный длинный текст, Telegram numeric author ID, phone/email, другие сообщения автора, message revisions и score breakdown. Local UI link не включается, потому что UI слушает только loopback.

Telegram request использует `sendMessage`, `parse_mode=HTML`, отключённый link preview и итоговую длину не более 4096 символов. User content всегда escaped.

## 8. Состав system notification

Порядок полей:

1. `⚠️ Системная ошибка`;
2. русская label component;
3. error code;
4. detected time в `Europe/Moscow`;
5. correlation ID.

Stack trace, file contents, credentials, Telegram session path и bot token не включаются.

## 9. Delivery state machine

```text
queued → delivering → sent
delivering/error_response → retry_wait → queued
error_response after attempt 5 → dead
delivering without confirmed response → dead (`delivery_uncertain`)
```

- worker атомарно claims одну outbox row lease длительностью 60 секунд;
- перед HTTP request создаётся committed `NotificationDelivery(status=sending)`;
- успешный Bot API response сохраняет returned Telegram message ID и переводит event в `sent`;
- подтверждённый error response создаёт retry по §10;
- timeout, connection reset после начала request или restart с abandoned `sending` считаются uncertain delivery;
- uncertain delivery автоматически не повторяется и становится `dead` с error code `delivery_uncertain`;
- это исключает автоматический duplicate при неизвестном результате запроса;
- operator может вручную повторить dead event из Dashboard; для `delivery_uncertain` требуется ввод `ПОВТОРИТЬ`.

## 10. Retry policy

Всего выполняется не более пяти автоматических attempts по абсолютным offsets от `outbox.created_at`:

| Attempt | Offset |
|---:|---:|
| 1 | сразу |
| 2 | 1 минута |
| 3 | 5 минут |
| 4 | 30 минут |
| 5 | 120 минут |

- после пятой подтверждённой ошибки event получает `dead`;
- если Bot API сообщает более длинный `retry_after`, attempt выполняется в `max(schedule_offset, retry_after)`;
- process restart не сбрасывает attempt count и `available_at`;
- manual retry переводит dead event в `queued`, обнуляет automatic attempt counter и добавляет `manual_retry_count`;
- manual retry использует тот же idempotency key и ту же outbox row.

## 11. Telegram Bot API error handling

| Результат | Поведение |
|---|---|
| HTTP 200 и `ok=true` | Сохранить message ID, state `sent` |
| HTTP response с `ok=false` | Записать Telegram error code/description, применить retry |
| HTTP 429 | Учесть `retry_after` и применить retry |
| HTTP 5xx | Применить retry |
| HTTP 4xx | Применить retry; после пятой ошибки `dead` |
| Timeout/reset после начала request | `delivery_uncertain`, без automatic retry |
| Invalid response JSON | `delivery_uncertain`, без automatic retry |

В logs Telegram description ограничивается 300 символами и проходит secret redaction.

## 12. Data model

### 12.1. `NotificationOutbox`

- `id`;
- `event_type`;
- `lead_id`/`incident_id`;
- `score_version` для lead event;
- `idempotency_key`;
- `schema_version`;
- `state`;
- `available_at`;
- `lease_expires_at`;
- `automatic_attempt_count`;
- `manual_retry_count`;
- `created_at`, `updated_at`.

### 12.2. `NotificationDelivery`

- `id`;
- `outbox_id`;
- `attempt_number`;
- `status`;
- `started_at`, `finished_at`;
- `http_status`;
- `telegram_error_code`;
- `telegram_message_id`;
- `error_code`;
- `correlation_id`.

Outbox terminal rows и deliveries хранятся 30 дней. Bot token и rendered notification body в этих таблицах не сохраняются.

## 13. Functional requirements

| ID | Требование | Приоритет | Acceptance criteria |
|---|---|---:|---|
| NOT-001 | Hot eligibility соответствует §5 | MUST | Warm/cold/irrelevant не создают outbox event |
| NOT-002 | Outbox создаётся атомарно с LeadScore | MUST | Fault injection не оставляет event без score или score без eligible event |
| NOT-003 | Idempotency key имеет установленный формат | MUST | Replay создаёт одну outbox row |
| NOT-004 | Excerpt ограничен 500 Unicode code points | MUST | Более длинный текст truncates с `…` |
| NOT-005 | Notification content HTML-escaped | MUST | User markup не меняет структуру message |
| NOT-006 | Retry offsets равны 0/1/5/30/120 минут | MUST | Persisted available_at соответствует schedule |
| NOT-007 | Пятая подтверждённая ошибка даёт dead | MUST | Шестой automatic attempt отсутствует |
| NOT-008 | Uncertain delivery не повторяется автоматически | MUST | Event становится dead с отдельным error code |
| NOT-009 | Delivery state виден в Dashboard | MUST | Отображаются attempts, result и error code |
| NOT-010 | System events ограничены тремя типами | MUST | Другие health changes не создают Telegram alert |
| NOT-011 | Один incident не создаёт alert storm | MUST | Повтор probe до recovery не создаёт event |
| NOT-012 | Bot token читается только из environment | MUST | Token отсутствует в SQLite и logs |
| NOT-013 | Automatic reply отсутствует | MUST | Модуль вызывает только Bot API для configured operator chat |
| NOT-014 | Lead notification latency p95 не превышает 30 секунд | MUST | Нагрузочный тест подтверждает target при healthy Bot API |
| NOT-015 | Quiet hours отсутствуют | MUST | Eligible event сразу получает первый attempt |

## 14. Startup и shutdown

Startup:

1. проверить наличие token и chat ID;
2. выполнить `getMe`;
3. восстановить expired leases;
4. перевести abandoned `sending` в `delivery_uncertain`, затем `dead`;
5. запустить один notification worker.

Graceful shutdown:

- перестать claim новые events;
- дождаться активного HTTP request не более 15 секунд;
- зафиксировать confirmed response;
- при отсутствии подтверждённого response сохранить uncertain delivery;
- закрыть `httpx.AsyncClient`.

## 15. Observability

Обязательные metrics:

- `notification_outbox_depth{state}`;
- `notification_oldest_ready_age_seconds`;
- `notification_attempts_total{outcome}`;
- `notification_delivery_latency_seconds`;
- `notification_dead_total{error_code}`;
- `notification_uncertain_total`;
- `notification_bot_health`;
- `notification_incidents_total{event_type}`.

Structured logs содержат outbox ID, event type, lead/incident internal ID, attempt, status, duration, HTTP status и correlation ID. Token, chat ID, message text и rendered body не логируются.

## 16. Dependencies

- upstream: Lead Scoring, Administration/Observability;
- storage: Lead Storage transactional outbox;
- settings: Operator Settings;
- security: environment secret handling;
- network: Telegram Bot API через `httpx`.

## 17. Acceptance test catalogue

| Test ID | Проверка | Ожидаемый результат |
|---|---|---|
| AT-NOT-001 | Созданы hot, warm и cold leads | Outbox event создан только для hot |
| AT-NOT-002 | Fault injection происходит между Score и Outbox | Transaction не оставляет частичный результат |
| AT-NOT-003 | Scoring event повторён 100 раз | Существует одна outbox row с установленным key |
| AT-NOT-004 | Text длиннее 500 code points | Excerpt ограничен и заканчивается `…` |
| AT-NOT-005 | Message text содержит HTML | Telegram получает escaped text |
| AT-NOT-006 | Четыре errors, затем success | Attempts происходят по offsets 0/1/5/30/120 |
| AT-NOT-007 | Пять подтверждённых errors | State dead, шестого attempt нет |
| AT-NOT-008 | Timeout после request start | State dead с delivery_uncertain, auto retry отсутствует |
| AT-NOT-009 | Delivery завершился error | Dashboard показывает attempts, result и error code |
| AT-NOT-010 | Некритичный health event создан | Telegram system event отсутствует |
| AT-NOT-011 | Collector error повторяется 20 probes | Создан один system event до recovery |
| AT-NOT-012 | Выполнен scan SQLite и logs | Bot token отсутствует |
| AT-NOT-013 | Проверены все исходящие Bot API requests | Destination всегда равен operator chat, reply автору отсутствует |
| AT-NOT-014 | Выполнен healthy pipeline load test | p95 delivery latency не более 30 секунд |
| AT-NOT-015 | Hot event создан в любое время суток | Первый attempt выполняется сразу |

## 18. DEFERRED

- warm/cold notifications;
- digest и quiet hours;
- несколько recipients;
- email/SMS/push channels;
- interactive Telegram buttons;
- attachment forwarding.

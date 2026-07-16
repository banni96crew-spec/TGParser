# Decision Log

Все записи имеют статус `accepted`. Этот документ не содержит вариантов выбора или незаполненных решений.

| ID | Дата | Решение | Причина | Модули |
|---|---|---|---|---|
| D-001 | 15.07.2026 | Один локальный оператор; multi-user и RBAC отсутствуют | Минимальная сложность персонального инструмента | `SET`, `UI`, `SEC` |
| D-002 | 15.07.2026 | RU-first UI и документация | Основной язык оператора и corpus | Все |
| D-003 | 15.07.2026 | Только публичные sources после ручного approve | Контролируемый source scope | `SRC`, `COL` |
| D-004 | 15.07.2026 | AI/LLM, embeddings и semantic search отсутствуют | Детерминированность и объяснимость | `DET`, `SCR` |
| D-005 | 15.07.2026 | Python 3.12.x | Зрелая экосистема и совместимость | `INF` |
| D-006 | 15.07.2026 | Telethon 1.44.x доступен только через `TelegramGateway` | Изоляция внешней библиотеки | `COL` |
| D-007 | 15.07.2026 | Один process с независимыми asyncio services | Простая локальная эксплуатация | `INF`, все runtime-модули |
| D-008 | 15.07.2026 | FastAPI, Uvicorn, Jinja2, HTMX и обычный CSS | UI без отдельного frontend build | `UI`, `INF` |
| D-009 | 15.07.2026 | SQLite + SQLAlchemy 2.x + Alembic + aiosqlite | Локальная БД с явными migrations | `STO`, `INF` |
| D-010 | 15.07.2026 | WAL, `foreign_keys=ON`, `busy_timeout=5000`, один logical writer | Предсказуемая конкурентная запись | `STO` |
| D-011 | 15.07.2026 | Persisted job table и внутренние workers; Redis/Celery отсутствуют | Не нужна отдельная инфраструктура | `STO`, `INF`, `OBS` |
| D-012 | 15.07.2026 | Settings в SQLite; secrets в environment/ACL-protected files | Разделение обычных параметров и секретов | `SET`, `SEC` |
| D-013 | 15.07.2026 | Web bind только `127.0.0.1`, login screen отсутствует | Персональный локальный режим | `SET`, `SEC`, `UI` |
| D-014 | 15.07.2026 | Notification gateway вызывает Bot API через `httpx` | Минимальная зависимость для отправки | `NOT` |
| D-015 | 15.07.2026 | Windows 10/11 x64, `uv`, `pyproject.toml`, lock-файл | Целевая рабочая среда | `INF` |
| D-016 | 15.07.2026 | Автозапуск через Task Scheduler с restart-on-failure | Проще отдельного service wrapper | `INF` |
| D-017 | 15.07.2026 | Discovery запускается вручную, depth `2`, expansion cap `25`, candidate cap `100` | Ограниченный и понятный crawl | `SRC` |
| D-018 | 15.07.2026 | Initial backfill `14 дней` или `3000 messages` | Достаточный calibration history | `COL` |
| D-019 | 15.07.2026 | Startup reconciliation batch `5000`; periodic каждые `15 минут`, batch `1000` | Быстрое восстановление при bounded нагрузке | `COL` |
| D-020 | 15.07.2026 | FloodWait ожидается полностью; account switching отсутствует | Один предсказуемый session owner | `COL` |
| D-021 | 15.07.2026 | `regex`, timeout `50 ms`, input cap `4096 chars` | Защита processing loop | `DET` |
| D-022 | 15.07.2026 | Активный `RuleSetVersion` immutable; изменение создаёт новую version | Воспроизводимость результатов | `DET`, `SCR` |
| D-023 | 15.07.2026 | Positive categories: direct order, contractor search, recommendation request, potential need | Покрытие коммерческого намерения | `DET` |
| D-024 | 15.07.2026 | Vacancy, advertising и spam — hard exclusions | Снижение информационного шума | `DET`, `SCR` |
| D-025 | 15.07.2026 | Score weights `25/20/15/10/5/5/5/5/5/5`, soft penalty cap `-30` | Понятная шкала `0–100` | `SCR` |
| D-026 | 15.07.2026 | Bands: hot `70–100`, warm `50–69`, cold `30–49`, irrelevant `0–29` | Консервативный порог hot | `SCR`, `UI`, `NOT` |
| D-027 | 15.07.2026 | Exact repost window `30 дней`; canonical выбирается по date/source/message | Детерминированный dedupe | `PROC`, `STO` |
| D-028 | 15.07.2026 | Fuzzy dedupe отсутствует в MVP | Исключение ошибочных склеиваний | `PROC` |
| D-029 | 15.07.2026 | Lead data `180 дней`; non-lead text `30`; outcome/hash `90`; logs/deliveries `30`; metrics `90`; CSV `1 час` | Контролируемый рост локального storage | `STO`, `OBS`, `UI` |
| D-030 | 15.07.2026 | Scheduled purge ежедневно `04:00` | Регулярная очистка после backup | `STO`, `INF` |
| D-031 | 15.07.2026 | Уведомления только для hot leads и critical system failures | Минимум шума | `NOT`, `OBS` |
| D-032 | 15.07.2026 | Notification retries: сразу, `1`, `5`, `30`, `120 минут`; затем `dead` | Bounded delivery recovery | `NOT` |
| D-033 | 15.07.2026 | Daily online backup `03:00`, `7` daily и `4` weekly; session исключён | Простое восстановление данных | `INF`, `SEC` |
| D-034 | 15.07.2026 | Calibration corpus минимум `500 messages / 10 sources`, precision `80%`, direct-order recall `70%`, negative false-positive rate `5%` | Измеримый quality gate | `DET`, `SCR`, `OBS` |
| D-035 | 15.07.2026 | p95 processing `10 s`, p95 notification `30 s`, gap recovery `20 min`, restart recovery `5 min`, duplicate rate `0` | Измеримый operational gate | `COL`, `PROC`, `NOT`, `OBS`, `INF` |
| D-036 | 15.07.2026 | Automatic outreach, private auto-join и account rotation отсутствуют | Жёсткая граница MVP | `SRC`, `COL`, `UI`, `NOT` |
| D-037 | 15.07.2026 | Lead и outbox создаются одной transaction; delivery idempotency key уникален | Нет потерянных или двойных alerts | `STO`, `NOT` |
| D-038 | 15.07.2026 | Source Registry в SQLite — единственный authoritative source; seed files только импорт | Нет конкурирующих конфигураций | `SRC`, `STO`, `SET` |
| D-039 | 16.07.2026 | `TelegramGateway` в `INTEGRATION_CONTRACTS` авторитетен: `connect`, `disconnect`, `resolve_public_source`, `validate_source`, `get_recommendations`, `iter_history`, `iter_updates`, `get_message`; `GatewayFloodWait(until)`; envelope `message_new\|message_edited\|message_deleted`; методы `iter_messages`/`register_live_handler` удалены | Единый port surface для COL/SRC без расхождения owner PRD | `COL`, `SRC` |
| D-040 | 16.07.2026 | Pipeline: claim → revision → normalize → identity dedupe → exact repost canonical → detection → scoring → persist lead/outbox → processing ack; `CollectorCheckpoint` обновляется только в TX с envelope (COL), не внутри `PersistProcessingResult` | Canonical до DET; checkpoint durability отделён от lead/outbox TX | `PROC`, `COL`, `STO` |
| D-041 | 16.07.2026 | DET-A правила получают нормативные `dimension`+`weight`; SCR потребляет веса из `DetectionResult.matched_rules` без изобретения; `matched_excerpt` ≤120 code points | Воспроизводимый score input и объяснимость | `DET`, `SCR` |
| D-042 | 16.07.2026 | `Lead.band` = `hot\|warm\|cold\|irrelevant`; Lead создаётся только для hot/warm/cold; rescore в irrelevant сохраняет Lead с `band=irrelevant` | Согласование DOMAIN с SCR/Inbox semantics | `SCR`, `STO`, `UI` |
| D-043 | 16.07.2026 | Acceptance catalogue `AT-STO-NNN` тестирует ровно `STO-NNN`; `AT-COL-018` ожидает terminal state `dead` после пяти transient retries | Traceability 1:1 без смыслового drift | `STO`, `COL` |
| D-044 | 16.07.2026 | Critical codes: `collector_stopped`, `telegram_session_unavailable`, `migration_failed`, `integrity_check_failed`; `NotificationOutbox.lead_id`/`incident_id`/`score_version` nullable; ровно один из lead или incident; агрегация `database_startup_failed` удалена | Единая taxonomy OBS→NOT | `OBS`, `NOT`, `STO` |
| D-045 | 16.07.2026 | Канонические env: `TG_API_ID`, `TG_API_HASH`, `TG_BOT_TOKEN`, `TG_NOTIFY_CHAT_ID`; `TLD_TELEGRAM_BOT_TOKEN` и SQLite chat id как secret store запрещены | Единый SEC/SET surface для secrets | `SET`, `SEC`, `NOT` |
| D-046 | 16.07.2026 | `SettingChange.reason` + `change_source` `ui\|startup_seed\|migration\|system`; semantic owner `BackupManifest` = INF, STO даёт primitives; `source_type` `channel\|megagroup\|group`; discovery methods `manual`, `seed_import`, `recommendation`, `public_link`, `mention`, `forward_origin`; `matched_excerpt` max 120 | Закрытие enum/ownership drift | `SET`, `INF`, `STO`, `SRC`, `DET` |
| D-047 | 16.07.2026 | `notifications.delivery_mode` = `shadow\|live` (default `shadow`); в shadow или при missing secrets MUST NOT insert `hot_lead` outbox; Leads создаются; critical OBS events эмитятся; critical outbox только при `live`+secrets; `shadow→live` не flush backlog | Controlled pilot без ложной доставки | `SET`, `NOT`, `STO`, `OBS` |

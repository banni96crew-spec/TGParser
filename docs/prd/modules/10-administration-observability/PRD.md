# PRD 10 — Administration, Logs and Monitoring

## 1. Назначение и границы

Модуль предоставляет единому оператору локальную техническую панель состояния, структурированные журналы, метрики, управление persisted jobs и безопасные recovery-действия.

Модуль наблюдает runtime-компоненты, но не реализует их бизнес-логику.

## 2. Goals и non-goals

### Goals

- За секунды показать, работает ли сбор и обработка сообщений.
- Обнаруживать остановку collector, недоступность Telegram session и ошибки migration/integrity check.
- Обеспечить проверяемое восстановление после restart за 5 минут.
- Дать оператору безопасные ручные действия над jobs без прямого редактирования БД.

### Non-goals

- Внешний SaaS-мониторинг.
- Распределённый tracing и отдельный telemetry cluster.
- Редактирование сообщений, лидов или rule sets из административной панели.

## 3. Принятые решения

- Наблюдаемость встроена в один Python-процесс и доступна через локальный FastAPI UI.
- Logs — JSON Lines в UTF-8 с ежедневной ротацией и хранением 30 дней.
- Metrics — агрегаты по 5-минутным UTC-buckets в SQLite, хранение 90 дней.
- Health statuses: `starting`, `healthy`, `degraded`, `blocked`, `unhealthy`, `stopped`.
- Cleanup запускается ежедневно в `04:00 Europe/Moscow`.
- Критические технические события создают outbox notification.
- Все ручные административные действия создают audit event без секретов и message text.

## 4. Functional requirements

| ID | Требование |
|---|---|
| OBS-001 | Dashboard MUST показывать process uptime, DB status, Telegram session status, live collector status, reconciliation lag, processing queue depth, outbox depth, last backup и last cleanup. |
| OBS-002 | Каждый компонент MUST публиковать heartbeat не реже одного раза в 30 секунд. |
| OBS-003 | Компонент MUST стать `unhealthy`, если heartbeat отсутствует 90 секунд; collector дополнительно создаёт critical event. |
| OBS-004 | Structured log MUST содержать UTC timestamp, level, event_name, component, correlation_id, result, duration_ms и безопасный context. |
| OBS-005 | Logs MUST исключать credentials, session contents, bot token и полный текст сообщений. |
| OBS-006 | Metrics MUST агрегироваться в 5-минутные buckets и очищаться после 90 дней. |
| OBS-007 | Processing logs MUST очищаться после 30 дней ежедневным cleanup job. |
| OBS-008 | Административная панель MUST разрешать pause/resume monitoring source, retry failed job, requeue dead outbox item и запуск reconciliation. |
| OBS-009 | Любое действие MUST требовать confirmation screen и idempotency key. |
| OBS-010 | Dashboard MUST показывать persisted job states `queued`, `running`, `succeeded`, `retry_wait`, `failed`, `dead`, `cancelled`. |
| OBS-011 | Job, оставшийся `running` без heartbeat 5 минут, MUST атомарно вернуться в `queued` при startup recovery. |
| OBS-012 | Critical events MUST включать `collector_stopped`, `telegram_session_unavailable`, `migration_failed`, `integrity_check_failed`. |
| OBS-013 | UI MUST показывать p95 live-to-lead, p95 lead-to-notification, duplicate counters и reconciliation recovery duration. |
| OBS-014 | System readiness MUST вычисляться только при доступной БД, успешных migrations, успешном integrity check и загруженном settings snapshot. |
| OBS-015 | Liveness endpoint `/health/live` MUST отвечать без обращения к Telegram; readiness endpoint `/health/ready` MUST проверять локальные обязательные зависимости. |
| OBS-016 | Dashboard MUST показывать размер calibration corpus, число источников, precision `hot + warm`, recall `direct_order` и false positive rate для `vacancy/advertising/spam`. |
| OBS-017 | Система MUST публиковать keyword discovery metrics: `discovery_runs_total{state}`, `discovery_queries_total{kind,outcome}`, `discovery_search_hits_total{kind}`, `discovery_unique_sources_total`, `discovery_verified_sources_total`, `discovery_qualified_evidence_total`, `discovery_promotions_total{result}`, `discovery_flood_wait_seconds`, `discovery_quota_skipped_total`, `discovery_run_duration_seconds`, `discovery_score_total{band}`. Labels MUST NOT включать query text, source title, username, run ID или Telegram ID. |
| OBS-018 | Health MUST включать component `discovery` со состояниями `healthy`, `degraded` (длительный FloodWait / частые transient errors), `blocked` (нет credentials / unauthorized/frozen), `stopped` (worker не запущен). Исчерпание free quota само по себе MUST NOT делать приложение unhealthy. |
| OBS-019 | Система MUST публиковать novelty/suppress/exhaustion metrics aligned with SRC-037/038: `discovery_novel_presented_total`, `discovery_registry_suppressed_total`, `discovery_dismissed_suppressed_total`, `discovery_cooldown_suppressed_total`, `discovery_pool_exhausted_total{reason}`, `discovery_novelty_ratio`. Labels MUST NOT включать query text, source title, username, run ID или Telegram ID. |
| OBS-020 | Loop health MUST reflect named runtime loops (INF-022): discovery claim, collector jobs, live updates, processing claim, notification outbox, reconciliation, health watchdog. Collector MUST NOT be reported permanent `STOPPED`/`deferred` when Telegram credentials and monitoring sources exist (D-066). |
| OBS-021 | Capacity/latency/recovery metric names MUST cover NFR-PERF-006..008 / NFR-REL-008: monitoring source count, ingestion rate, burst backlog age, p95 `received_at→processed_at`, restart recovery duration, exact-dedupe counters. |

## 5. Acceptance criteria

| ID | Проверяемый результат |
|---|---|
| AT-OBS-001 | Dashboard отображает все девять утверждённых operational status indicators из OBS-001. |
| AT-OBS-002 | Каждый запущенный компонент публикует минимум два heartbeat за 60 секунд. |
| AT-OBS-003 | После остановки heartbeat collector получает `unhealthy` не позднее 90 секунд и создаётся одно critical event. |
| AT-OBS-004 | JSON log содержит все обязательные поля и валидный UTC timestamp. |
| AT-OBS-005 | Искусственно добавленные credentials, session contents, bot token и message text отсутствуют в сохранённом JSON log. |
| AT-OBS-006 | Metric observations попадают в 5-минутные buckets; cleanup удаляет buckets старше 90 дней и сохраняет более новые. |
| AT-OBS-007 | Cleanup удаляет processing logs старше 30 дней и сохраняет более новые. |
| AT-OBS-008 | Каждое из четырёх утверждённых admin actions успешно выполняется через публичную команду и отражается в UI. |
| AT-OBS-009 | Без confirmation действие не отправляется; повтор POST с тем же idempotency key выполняет действие один раз. |
| AT-OBS-010 | Dashboard корректно отображает каждое из семи утверждённых job states. |
| AT-OBS-011 | Startup recovery возвращает job без heartbeat 5 минут в очередь, не дублируя committed result. |
| AT-OBS-012 | Каждое из четырёх критических событий создаёт ровно один `critical.system_event.v1` (в т.ч. при `delivery_mode=shadow`); Telegram critical outbox — только при `live`+secrets. |
| AT-OBS-013 | Dashboard отображает p95 live-to-lead ≤10 секунд, lead-to-notification ≤30 секунд, 0 duplicates и recovery не более 20 минут на принятом тестовом наборе. |
| AT-OBS-014 | После restart система достигает readiness не более чем за 5 минут при исправных зависимостях; каждая обязательная неисправность отдельно переводит её в not-ready. |
| AT-OBS-015 | `/health/live` отвечает при недоступном Telegram; `/health/ready` возвращает failure при ошибке migration или integrity check. |
| AT-OBS-016 | Remediation release quality gate (D-067): corpus ≥ 500 messages from ≥ 10 sources; hot precision ≥ 0.80; hot+warm precision ≥ 0.70; purchase-intent / `direct_order` recall ≥ 0.75; false-positive rate for `vacancy/advertising/spam` ≤ 5%. Historical MVP wording hot+warm ≥ 80% / `direct_order` recall ≥ 70% is superseded for remediation and MUST NOT be treated as a live gate. Dashboard still displays the OBS-016 metric fields. |
| AT-OBS-017 | Keyword discovery metrics публикуются с утверждёнными именами; запрещённые labels отсутствуют. |
| AT-OBS-018 | Component `discovery` отражает `healthy`/`degraded`/`blocked`/`stopped`; quota exhaustion alone не ставит app unhealthy. |
| AT-OBS-019 | Novelty/suppress/exhaustion metrics published with approved names; forbidden labels absent. |
| AT-OBS-020 | With credentials + monitoring sources, collector loop is not permanent deferred/STOPPED; named loops report heartbeats. |
| AT-OBS-021 | Capacity/latency/recovery metric names present for monitoring capacity, burst drain, p95 received-to-processed, and restart recovery. |

## 6. Входные и выходные контракты

### Входы

- `ComponentHeartbeat(component, instance_id, observed_at, details)`.
- `MetricObservation(name, value, labels, observed_at)`.
- `StructuredLogEvent`.
- `AdminCommand(action, target_type, target_id, idempotency_key)`.

### Выходы

- `SystemHealthSnapshot`.
- `critical.system_event.v1`.
- `AdminActionResult`.
- Локальные `/health/live`, `/health/ready` и страницы `/admin`.

## 7. Data ownership

Модуль владеет:

- `ComponentHealth`.
- `MetricBucket`.
- `AdminAction`.

`ProcessingLog` принадлежит Message Processing и читается модулем через query contract. Persisted jobs и outbox принадлежат Storage; модуль использует их публичные команды.

## 8. Состояния и переходы

- Health: startup даёт `starting`; успешная полная проверка — `healthy`; частичный сбой — `degraded`; отсутствие обязательной configuration/session — `blocked`; потеря heartbeat — `unhealthy`; ручная остановка — `stopped`. Успешная полная повторная проверка восстанавливает `healthy`.
- Job: `queued → running → succeeded`; ошибка даёт `retry_wait → queued`, после исчерпания попыток — `dead`; разрешена ручная отмена `queued/retry_wait → cancelled`.
- System readiness: `starting → ready`; ошибка обязательной зависимости даёт `not_ready`; успешная повторная проверка возвращает `ready`.

## 9. Ошибки, retries и recovery

- Запись log не должна откатывать бизнес-транзакцию; отказ фиксируется fallback-сообщением в stderr.
- Неуспешная запись metric повторяется один раз через 5 секунд, затем увеличивает in-memory counter.
- Stale running jobs восстанавливаются на startup по lease timeout 5 минут.
- Dead job не перезапускается автоматически; ручной requeue создаёт новую attempt с тем же business idempotency key.

## 10. Security requirements

- Admin UI доступен только на loopback listener.
- POST-действия используют same-origin, CSRF token, confirmation и idempotency key.
- Logs и metrics не содержат секретов и полного текста Telegram messages.
- Идентификаторы файлов и пути отображаются только относительно application data directory.

## 11. Observability

Модуль наблюдает сам себя через `observability_event_drop_total`, `metric_write_failure_total`, `log_write_failure_total`, `stale_job_recovered_total` и heartbeat `administration_observability`.

## 12. Dependencies

- Upstream: Storage, Settings, Security, Deployment.
- Наблюдаемые модули: Discovery, Collector, Processing, Detection, Scoring, Notifications и Dashboard.
- Downstream: Dashboard для встроенной admin-navigation, Notifications для critical events.

## 13. MVP и исключённые функции

### MVP

- Health/readiness, structured logs, metrics, job controls и critical events.
- Success metrics dashboard и cleanup scheduling.

### DEFERRED

- Экспорт обезличенных metric aggregates.

### Исключено

- Prometheus/Grafana, distributed tracing и внешний log collector.

## 14. Acceptance test catalogue

- `OBS-HEALTH`: AT-OBS-001, AT-OBS-002, AT-OBS-003, AT-OBS-010, AT-OBS-011, AT-OBS-012, AT-OBS-014, AT-OBS-015, AT-OBS-018, AT-OBS-020.
- `OBS-REDACTION`: AT-OBS-004, AT-OBS-005.
- `OBS-ADMIN`: AT-OBS-008, AT-OBS-009.
- `OBS-RETENTION`: AT-OBS-006, AT-OBS-007.
- `OBS-MVP-METRICS`: AT-OBS-013, AT-OBS-016, AT-OBS-017, AT-OBS-019, AT-OBS-021.

## 15. Decision log references

- DEC-003: single-process async runtime.
- DEC-010: persisted jobs with internal asyncio workers.
- DEC-018: technical retention schedule.
- DEC-021: measurable MVP readiness targets.

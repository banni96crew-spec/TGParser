# Shared Quality Requirements

## 1. Performance

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-PERF-001` | p95 live update → committed Lead ≤ `10 s` | Нагрузка `10 messages/s` в течение `10 min`, corpus mix, gate выполнен |
| `NFR-PERF-002` | p95 committed hot Lead → notification ≤ `30 s` | Bot API test gateway без искусственной задержки |
| `NFR-PERF-003` | Inbox first page ≤ `1 s` для `100,000 messages / 10,000 leads` | Локальный benchmark на целевой Windows host |
| `NFR-PERF-004` | Rule processing p95 ≤ `100 ms/message` | Активный DET-A corpus; каждый regex timeout ≤ `50 ms` |
| `NFR-PERF-005` | UI pagination не загружает более `100 leads/request` | Route contract и query plan test |

## 2. Reliability

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-REL-001` | Duplicate Leads в exact replay — `0` | Один update повторён `100` раз и обработан параллельно |
| `NFR-REL-002` | Duplicate notifications в replay — `0` | Outbox worker crash на каждом transaction boundary |
| `NFR-REL-003` | Live gap восстановлен ≤ `20 min` | Искусственный disconnect на `10 min`, затем reconciliation |
| `NFR-REL-004` | Restart recovery ≤ `5 min` | Kill process во время jobs/outbox, Task Scheduler restart |
| `NFR-REL-005` | Checkpoint не опережает committed message | Fault injection до и после commit |
| `NFR-REL-006` | FloodWait не создаёт Telegram retry до `until` | Fake gateway с server wait |
| `NFR-REL-007` | Migration и backup restore сохраняют referential integrity | `foreign_key_check` и `integrity_check` возвращают `ok` |

## 3. Classification quality

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-QLT-001` | Calibration corpus ≥ `500 messages` из ≥ `10 sources` | Corpus manifest содержит counts и labels |
| `NFR-QLT-002` | Precision `hot + warm` ≥ `80%` | Fixed corpus, active rule checksum |
| `NFR-QLT-003` | Recall `direct_order` ≥ `70%` | Fixed corpus, confusion matrix |
| `NFR-QLT-004` | False-positive rate negative categories ≤ `5%` | Vacancy/advertising/spam labeled subset |
| `NFR-QLT-005` | Один input + revision + ruleset даёт одинаковый result | `100` повторных runs, byte-equivalent structured result |

## 4. Security

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-SEC-001` | Web server слушает только `127.0.0.1` | Socket inspection после startup |
| `NFR-SEC-002` | Secrets/session отсутствуют в database, logs, exports и backups | Automated token/session canary scan |
| `NFR-SEC-003` | Session и secret files доступны только текущему Windows user и SYSTEM | ACL inspection test |
| `NFR-SEC-004` | State-changing HTTP routes защищены CSRF token и same-origin checks | Negative request suite |
| `NFR-SEC-005` | User text безопасно escaped в HTML и Telegram formatting | Injection corpus test |
| `NFR-SEC-006` | Regex не блокирует event loop | Pathological DET-A suite с timeout |

## 5. Maintainability

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-MNT-001` | Telethon imports существуют только в collector adapter package | Static import scan |
| `NFR-MNT-002` | HTTP routes не выполняют direct SQL | Static dependency test |
| `NFR-MNT-003` | Domain modules не импортируют SQLAlchemy models | Static dependency test |
| `NFR-MNT-004` | Dependencies закреплены `uv.lock` | Clean sync воспроизводит environment |
| `NFR-MNT-005` | Schema change всегда имеет Alembic migration | CI сравнивает metadata и migration head |
| `NFR-MNT-006` | Requirement/test IDs уникальны | Documentation lint |

## 6. Observability

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-OBS-001` | Каждый job имеет correlation ID, state, counters и duration | Job detail API/UI test |
| `NFR-OBS-002` | Account, source, pipeline, outbox, DB и backup имеют health state | Health page показывает шесть component groups |
| `NFR-OBS-003` | Structured logs имеют stable event codes | JSON schema validation |
| `NFR-OBS-004` | Metrics сохраняются `90 дней`, logs `30 дней` | Time-controlled purge test |
| `NFR-OBS-005` | Critical failures создают один idempotent system alert | Fault injection и outbox inspection |

## 7. Data lifecycle

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-DATA-001` | Lead data очищается через `180 дней` после last activity | Time-controlled purge test |
| `NFR-DATA-002` | Non-lead text очищается через `30 дней` | Hash/outcome остаются, text отсутствует |
| `NFR-DATA-003` | Non-lead hash/outcome очищаются через `90 дней` | Связанные orphan records отсутствуют |
| `NFR-DATA-004` | Temporary CSV удаляется через `1 час` | Scheduled cleanup test |
| `NFR-DATA-005` | Daily purge стартует `04:00 Europe/Moscow` | Scheduler integration test |

## 8. Backup и recovery

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-BCK-001` | Online backup стартует ежедневно `03:00 Europe/Moscow` | Scheduler integration test |
| `NFR-BCK-002` | Rotation сохраняет `7 daily + 4 weekly` copies | Fake clock rotation suite |
| `NFR-BCK-003` | Session file отсутствует во всех copies | Backup content scan |
| `NFR-BCK-004` | Restore проверяет `integrity_check` до замены active DB | Corrupt backup rejected |
| `NFR-BCK-005` | Restore выполняется только при stopped runtime | Running-process restore rejected |

## 9. Test layers

- **Unit:** normalization, state transitions, rules, score, canonical choice, retry schedule.
- **Contract:** gateway DTO, application ports, outbox payload, observability event schemas.
- **Integration:** SQLite migrations, transactions, jobs, outbox, purge, backup/restore.
- **Adapter:** fake Telethon client и fake Bot API; реальные credentials не используются в automated suite.
- **End-to-end:** source approve → message → lead → inbox → notification.
- **Fault injection:** disconnect, FloodWait, database lock, process crash, corrupt backup, Bot API errors.
- **Calibration:** immutable labeled RU corpus с checksum.

## 10. Release gate

MVP release разрешён только при одновременном прохождении всех `NFR-*` требований и acceptance suites 12 модулей. Failed gate блокирует release, но не уничтожает собранные committed данные.

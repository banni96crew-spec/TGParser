# Shared Quality Requirements

## 1. Performance

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-PERF-001` | p95 live update → committed Lead ≤ `10 s` | Нагрузка `10 messages/s` в течение `10 min`, corpus mix, gate выполнен |
| `NFR-PERF-002` | p95 committed hot Lead → notification ≤ `30 s` | Bot API test gateway без искусственной задержки |
| `NFR-PERF-003` | Inbox first page ≤ `1 s` для `100,000 messages / 10,000 leads` | Локальный benchmark на целевой Windows host |
| `NFR-PERF-004` | Rule processing p95 ≤ `100 ms/message` | Активный DET-A corpus; каждый regex timeout ≤ `50 ms` |
| `NFR-PERF-005` | UI pagination не загружает более `100 leads/request` | Route contract и query plan test |
| `NFR-PERF-006` | Monitoring capacity: `100` sources / ≥ `1000` messages/day ingestion | Capacity harness (Wave 09); external volume reported separately |
| `NFR-PERF-007` | Burst `10` msg/s × `10` min (`6000` events); backlog drain ≤ `15` min | Fake gateway load harness |
| `NFR-PERF-008` | p95 `received_at→processed_at` ≤ `30 s` steady / ≤ `120 s` burst | Distinct from NFR-PERF-001 (live→Lead); same burst profile as PERF-007 |

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
| `NFR-REL-008` | Kill/restart reconciliation continues from checkpoint without gap/dup; restart recovery wall ≤ `5` min (align NFR-REL-004) | Process kill mid-job; resume jobs + checkpoint; exact dedupe `100%` (0 duplicate raw/lead/outbox on replay) |

## 3. Classification quality

| ID | Requirement | Acceptance criterion |
|---|---|---|
| `NFR-QLT-001` | Calibration corpus ≥ `500 messages` из ≥ `10` source types | Corpus manifest содержит counts и labels |
| `NFR-QLT-002` | Precision `hot + warm` ≥ `80%` | **Superseded for remediation release by `NFR-QLT-006` (D-067).** Historical MVP acceptance kept for non-remediation reports only. |
| `NFR-QLT-003` | Recall `direct_order` ≥ `70%` | **Superseded for remediation release by `NFR-QLT-006` (D-067)** where purchase-intent ≡ DET category/`direct_order` recall ≥ `0.75`. Historical MVP acceptance kept for non-remediation reports only. |
| `NFR-QLT-004` | False-positive rate negative categories ≤ `5%` | Vacancy/advertising/spam labeled subset |
| `NFR-QLT-005` | Один input + revision + ruleset даёт одинаковый result | `100` повторных runs, byte-equivalent structured result |
| `NFR-QLT-006` | Remediation calibration / discovery quality gates (single numeric source of truth, D-067 / plan §2) | Fixed corpus + discovery fixtures: hot precision ≥ `0.80`; hot+warm precision ≥ `0.70`; purchase-intent/`direct_order` recall ≥ `0.75`; permanent dismiss suppress recurrence = `0`; in-run canonical dedupe ≤ `1` presentation / canonical / run; novelty_ratio ≥ `0.80` after first run when replacement pool sufficient; live 5 sequential runs median pairwise Jaccard of presented canonical sets ≤ `0.60` OR each violating run has `pool_exhausted=true` with reason; UI bind `127.0.0.1` only |
| `NFR-QLT-007` | Working-client-search DET + discovery outcome gates (D-068) | Versioned labeled corpora with honest provenance: C01–C20 = operator run13 sanitized (owner labels; 3+/17− — not population alone); run14 regression = `operator_run_14_sanitized_excerpt` (not population); T1–T5 = DET-A golden (`det_a_golden`). Report C* / R14 / T* / combined separately; combined ≥ `0.80`/`0.80`. Soft-cap without quality → source `inconclusive`; run cap before pool exhaustion → gate `inconclusive` (not fail). Discovery: `6`≠quality, `7`=quality; `14`d; `1500`/`7500` caps; fair page waterfill; `4` quality → fail; `5×7`/35 → pass; exact-repost once |

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

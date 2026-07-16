# Requirements Traceability

## 1. Правило трассировки

Каждое module requirement `<PREFIX>-NNN` имеет acceptance test `AT-<PREFIX>-NNN` с тем же номером в PRD владельца. Таблица ниже является сводным индексом; точный scenario и expected result находятся в acceptance catalogue соответствующего модуля.

Изменение requirement без одновременного изменения одноимённого acceptance test запрещено.

## 2. Module requirements

| Module | Requirement range | Acceptance range | Owner document | Downstream verification |
|---|---|---|---|---|
| Source Discovery | `SRC-001..016` | `AT-SRC-001..016` | [PRD](modules/01-source-discovery/PRD.md) | Collector принимает только monitoring sources |
| Telegram Collector | `COL-001..020` | `AT-COL-001..020` | [PRD](modules/02-telegram-collector/PRD.md) | Processing получает versioned envelopes |
| Message Processing | `PROC-001..018` | `AT-PROC-001..018` | [PRD](modules/03-message-processing/PRD.md) | Detection получает одну eligible revision |
| Lead Detection | `DET-001..014` | `AT-DET-001..014` | [PRD](modules/04-lead-detection/PRD.md) | Scoring получает category/signals/rule IDs |
| Lead Scoring | `SCR-001..016` | `AT-SCR-001..016` | [PRD](modules/05-lead-scoring/PRD.md) | Storage/UI/Notifications получают immutable score |
| Lead Storage | `STO-001..014` | `AT-STO-001..014` | [PRD](modules/06-lead-storage/PRD.md) | Repositories, outbox и migrations integration suite |
| Lead Dashboard | `UI-001..016` | `AT-UI-001..016` | [PRD](modules/07-lead-dashboard/PRD.md) | End-to-end operator journeys |
| Notifications | `NOT-001..015` | `AT-NOT-001..015` | [PRD](modules/08-notifications/PRD.md) | Bot API adapter и outbox fault-injection suite |
| Operator Settings | `SET-001..015` | `AT-SET-001..015` | [PRD](modules/09-operator-settings/PRD.md) | Settings validation и local-access suite |
| Administration & Observability | `OBS-001..016` | `AT-OBS-001..016` | [PRD](modules/10-administration-observability/PRD.md) | Health, metrics, logs и recovery suite |
| Security | `SEC-001..015` | `AT-SEC-001..015` | [PRD](modules/11-security/PRD.md) | Static scan, ACL, CSRF, injection suite |
| Deployment & Infrastructure | `INF-001..020` | `AT-INF-001..020` | [PRD](modules/12-deployment-infrastructure/PRD.md) | Clean install, startup, backup/restore suite |

## 3. Shared quality requirements

| Requirement | Primary modules | Acceptance suite |
|---|---|---|
| `NFR-PERF-001` | `COL`, `PROC`, `DET`, `SCR`, `STO` | Live pipeline load test |
| `NFR-PERF-002` | `STO`, `NOT` | Outbox-to-Bot latency test |
| `NFR-PERF-003` | `STO`, `UI` | Large local database UI benchmark |
| `NFR-PERF-004` | `DET`, `SCR` | DET-A performance corpus |
| `NFR-PERF-005` | `UI`, `STO` | Pagination contract test |
| `NFR-REL-001` | `PROC`, `STO` | Exact replay suite |
| `NFR-REL-002` | `STO`, `NOT` | Outbox crash-boundary suite |
| `NFR-REL-003` | `COL`, `OBS` | Disconnect/reconciliation suite |
| `NFR-REL-004` | `INF`, `COL`, `STO`, `NOT` | Forced process restart suite |
| `NFR-REL-005` | `COL`, `STO` | Checkpoint transaction fault injection |
| `NFR-REL-006` | `COL` | Fake FloodWait gateway test |
| `NFR-REL-007` | `STO`, `INF` | Migration/restore integrity suite |
| `NFR-QLT-001` | `DET`, `SCR` | Corpus manifest validation |
| `NFR-QLT-002` | `DET`, `SCR`, `OBS` | Precision report |
| `NFR-QLT-003` | `DET`, `SCR`, `OBS` | Direct-order recall report |
| `NFR-QLT-004` | `DET`, `OBS` | Negative-category confusion matrix |
| `NFR-QLT-005` | `DET`, `SCR` | Deterministic repeated-run suite |
| `NFR-SEC-001` | `SET`, `SEC`, `INF` | Listener inspection |
| `NFR-SEC-002` | `SEC`, `STO`, `UI`, `INF` | Secret canary scan |
| `NFR-SEC-003` | `SEC`, `INF` | Windows ACL inspection |
| `NFR-SEC-004` | `SEC`, `UI` | CSRF/same-origin negative suite |
| `NFR-SEC-005` | `UI`, `NOT`, `SEC` | HTML/Telegram injection corpus |
| `NFR-SEC-006` | `DET` | Pathological regex suite |
| `NFR-MNT-001` | `COL` | Telethon import boundary scan |
| `NFR-MNT-002` | `UI`, `STO` | Route dependency scan |
| `NFR-MNT-003` | `STO`, domain modules | SQLAlchemy boundary scan |
| `NFR-MNT-004` | `INF` | Clean `uv sync --frozen` |
| `NFR-MNT-005` | `STO`, `INF` | Alembic metadata/head comparison |
| `NFR-MNT-006` | Все | Documentation ID lint |
| `NFR-OBS-001` | `STO`, `OBS` | Job detail integration test |
| `NFR-OBS-002` | `OBS`, все runtime modules | Health page component test |
| `NFR-OBS-003` | `OBS` | Structured event schema test |
| `NFR-OBS-004` | `OBS`, `STO` | Log/metric lifecycle test |
| `NFR-OBS-005` | `OBS`, `STO`, `NOT` | Critical alert idempotency test |
| `NFR-DATA-001` | `STO`, `UI` | Lead purge test |
| `NFR-DATA-002` | `STO` | Non-lead text purge test |
| `NFR-DATA-003` | `STO` | Non-lead graph purge test |
| `NFR-DATA-004` | `STO`, `UI`, `INF` | Temporary export cleanup test |
| `NFR-DATA-005` | `STO`, `INF` | Scheduler timezone test |
| `NFR-BCK-001` | `INF`, `STO` | Daily scheduler test |
| `NFR-BCK-002` | `INF` | Backup rotation fake-clock suite |
| `NFR-BCK-003` | `SEC`, `INF` | Backup content scan |
| `NFR-BCK-004` | `STO`, `INF` | Corrupt backup rejection test |
| `NFR-BCK-005` | `INF` | Running-process restore rejection test |

## 4. End-to-end journeys

| Journey | Requirements | Gate |
|---|---|---|
| Add and approve source | `SRC-001`, `SRC-007..014`, `COL-004..005`, `UI-006` | Candidate не мониторится до approve; backfill создаётся один раз |
| Live lead | `COL-006`, `PROC-001..004`, `DET-004..014`, `SCR-001..013`, `STO-001..004`, `UI-002..005`, `NOT-001..008` | Lead виден ≤10 s; hot alert ≤30 s |
| Disconnect recovery | `COL-007..010`, `COL-017..020`, `STO-010`, `OBS-001..016`, `INF-002..010` | Gap ≤20 min; duplicates `0` |
| Edit/delete/repost | `COL-013..015`, `PROC-005..014`, `STO-003..007`, `UI-012..014`, `NOT-009..015` | Revision/tombstone/canonical behavior детерминировано |
| Rule activation/re-score | `DET-001..006`, `DET-011..014`, `SCR-001..016`, `UI-007..011` | Immutable versions; historical score не перезаписан |
| Backup/restore | `STO-011..014`, `SEC-001..015`, `INF-011..020` | Integrity `ok`; session отсутствует; runtime stopped |

## 5. Release evidence

Release evidence включает:

- checksum active rule set и calibration corpus;
- requirement/test lint report;
- confusion matrix и latency percentiles;
- replay/fault-injection report;
- latest migration head;
- latest verified backup/restore result;
- secret scan result;
- список версий dependencies из lock-файла.

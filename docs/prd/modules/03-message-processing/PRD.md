# Модульный PRD 03 — Message Processing

## 1. Назначение и границы

Модуль преобразует Collector envelopes в устойчивую историю Telegram messages, нормализует текст, обрабатывает повторную доставку, edits и deletes, выполняет exact cross-source deduplication и запускает versioned detection/scoring pipeline.

Модуль отвечает за оркестрацию и техническую целостность, но не определяет категорию или score.

## 2. Goals и non-goals

### Goals

- Обеспечить exactly-once observable result поверх at-least-once доставки.
- Сохранить связь сообщения с источником, автором, датой и revisions.
- Детерминированно выбрать одно canonical message среди точных копий.
- Корректно пересчитать результат после edit и обработать delete.
- Восстановить незавершённую работу после crash без duplicate leads/outbox events.

### Non-goals

- Fuzzy или semantic deduplication.
- Rule definitions, category resolution и score weights.
- Telegram collection.
- Media/OCR и распознавание voice messages.
- Автоматическое исправление или перевод текста.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Telegram message identity | `(source_id, telegram_message_id)` |
| Normalization Unicode form | `NFKC` |
| Text hash | SHA-256 от UTF-8 normalized dedup text |
| Cross-source duplicate window | `30 дней` |
| Canonical order | `published_at`, затем internal `source_id`, затем Telegram message ID |
| Fuzzy/semantic dedup | Отсутствует |
| Максимум текста для detection | Первые `4096` Unicode code points |
| Job lease | `5 минут` |
| Lease heartbeat | Каждые `60 секунд` |
| Worker concurrency | `2` asyncio workers |
| Job retry | `1`, `5`, `30`, `120`, `600` секунд, затем failed |

## 4. Processing pipeline

### PROC-001 — Persisted inbox claim

Worker MUST атомарно claim один незавершённый `TelegramEventEnvelope` в порядке `received_at ASC, event_id ASC`. Claim устанавливает `processing_state=processing`, `lease_owner`, `lease_until=now+5min`, increment attempt и создаёт/обновляет persisted processing job.

Два asyncio workers выполняются в одном процессе. Один envelope не может одновременно принадлежать двум workers.

### PROC-002 — Pipeline stages

Для `new` или `edit` stages выполняются строго:

1. validate envelope schema;
2. upsert author metadata;
3. normalize display text и dedup text;
4. upsert message identity;
5. append revision при изменении content fingerprint;
6. update duplicate group и canonical flag;
7. вызвать Lead Detection для canonical non-deleted message;
8. вызвать Lead Scoring для положительного detection result;
9. записать processing result, lead mutation и outbox events;
10. отметить inbox record completed.

Stages 4–10 MUST выполняться одной SQLite-транзакцией. Внешние сетевые вызовы в транзакции отсутствуют.

### PROC-003 — Text normalization

`display_text` строится так:

1. null заменяется пустой строкой;
2. `CRLF` и `CR` заменяются на `LF`;
3. применяется Unicode `NFKC`;
4. удаляются `U+200B`, `U+200C`, `U+200D`, `U+2060`, `U+FEFF`;
5. более трёх последовательных `LF` сокращаются до двух;
6. trailing spaces каждой строки удаляются;
7. весь текст обрезается по краям.

`dedup_text` строится из `display_text`: любой Unicode whitespace sequence заменяется одним ASCII space, текст обрезается по краям и применяется Unicode `casefold()`. Пунктуация, URL и emoji сохраняются.

`analysis_text` равен первым `4096` Unicode code points `dedup_text`; усечение фиксируется `analysis_truncated=true`.

### PROC-004 — Content fingerprint

Content fingerprint равен SHA-256 от UTF-8 строки:

```text
display_text + "\n" + author_peer_id_or_empty + "\n" + edited_at_or_empty
```

Dedup hash равен SHA-256 UTF-8 `dedup_text`. Пустой `dedup_text` получает hash, но не участвует в cross-source duplicate grouping и detection.

## 5. Messages и revisions

### PROC-005 — Message upsert

Unique constraint `(source_id, telegram_message_id)` MUST предотвращать вторую message record. Повторный `new` с тем же content fingerprint завершается как `idempotent_replay` без revision и downstream rerun.

### PROC-006 — Initial revision

Первый непустой new/edit envelope создаёт revision `1`. Revision содержит immutable snapshot display text, dedup hash, author snapshot, Telegram timestamps, public link, forward origin и content fingerprint.

### PROC-007 — Edit

Edit с новым content fingerprint MUST создать revision `previous+1`, пометить её current и запустить dedup, detection и scoring заново. Предыдущая revision остаётся immutable. Edit с уже существующим fingerprint считается replay.

Если edit меняет dedup hash, message удаляется из старой duplicate group и включается в новую группу в той же транзакции.

### PROC-008 — Out-of-order edit

При нескольких edits current revision выбирается по `(telegram_edited_at DESC NULLS LAST, received_at DESC, event_id DESC)`. Поздно доставленная старая edit сохраняется как historical revision, но не запускает downstream rerun, если не стала current.

### PROC-009 — Delete

Delete MUST установить `deleted_at=received_at`, `message_state=deleted`, сохранить последний известный текст до его срока очистки и создать immutable delete processing result. Повторный delete идемпотентен.

Deleted message исключается из canonical selection. Если оно было canonical, выбирается следующий non-deleted member и публикуется `CanonicalMessageChanged`. Если активных members нет, связанный lead получает source state `deleted` и новое уведомление не создаётся.

## 6. Exact deduplication

### PROC-010 — Duplicate candidate set

Cross-source duplicate candidates имеют одинаковый dedup hash, разные `source_id`, non-empty dedup text, `deleted_at IS NULL` и `published_at` в интервале `candidate.published_at ± 30 days`.

Копии в одном source не объединяются cross-source; их Telegram identities остаются независимыми.

### PROC-011 — Duplicate group

Все связанные transitive candidates одного hash в 30-дневном окне образуют `DuplicateGroup`. Group key равен `<dedup_hash>:<UTC date earliest published_at YYYY-MM-DD>`. Внутренний integer group ID сохраняется при смене canonical.

### PROC-012 — Canonical selection

Canonical non-deleted member выбирается минимальным tuple:

1. `published_at`;
2. internal numeric `source_id`;
3. `telegram_message_id`.

Ровно один active member группы имеет `is_canonical=true`. Сообщение без cross-source matches является singleton group и canonical.

### PROC-013 — Canonical change

Если поздний backfill приносит более ранний member, canonical меняется атомарно. Существующий lead пере привязывается к новому canonical message без создания второго lead. Outbox idempotency использует duplicate group ID, event type и score version, поэтому ранее отправленное уведомление не повторяется.

### PROC-014 — Detection eligibility

Detection запускается только для current revision canonical non-deleted message с непустым `analysis_text`. Non-canonical member сохраняет processing result `duplicate_suppressed` и ссылку на canonical message.

## 7. Processing results, retry и recovery

### PROC-015 — Versioned processing result

Каждый фактический downstream run создаёт immutable `ProcessingResult` с message revision ID, rule set version, scoring version, category, score/band или null, matched rule IDs, explanation codes, started/finished timestamps и outcome.

### PROC-016 — Retry

Schema/validation errors являются permanent и сразу получают `failed_permanent`. SQLite busy/transient internal errors повторяются через `1`, `5`, `30`, `120`, `600` секунд. После пятой повторной ошибки job получает `failed`.

### PROC-017 — Lease recovery

Heartbeat продлевает lease каждые `60 секунд`. При startup или worker scan любая processing record с `lease_until < now` возвращается в `queued`. Transaction boundaries и unique constraints MUST обеспечивать ноль duplicate revisions, leads и outbox rows.

### PROC-018 — Manual replay

Administration UI MUST разрешать replay failed job и replay current message revision с выбранной активной rule/scoring version. Replay создаёт новый `ProcessingResult`, но не новую `TelegramMessageRevision`. Один job нельзя replay одновременно.

## 8. Data ownership

Модуль владеет `TelegramMessage`, `TelegramMessageRevision`, semantics `ProcessingJob`, `ProcessingResult`, `DuplicateGroup` и membership. Lead Detection владеет rule results, Lead Scoring — score details, Lead Storage — физической схемой, общей `Job` table и repositories.

Обязательные ограничения:

- unique `(source_id, telegram_message_id)`;
- unique `(message_id, revision_number)`;
- unique `(message_id, content_fingerprint)`;
- один current revision на message;
- один canonical active member на duplicate group;
- unique outbox idempotency key.

## 9. Security requirements

- Message text отсутствует в structured logs и metric labels.
- Error UI показывает message ID, stage и error code; stack trace доступен только в локальном technical log.
- CSV/HTML rendering экранирует пользовательский текст на output boundary.
- Regex выполняется только модулем Lead Detection с timeout.

## 10. Observability

Metrics:

- `processing_jobs_total{outcome,stage}`;
- `processing_duration_seconds{outcome}`;
- `processing_queue_depth{state}`;
- `processing_retries_total{reason}`;
- `message_revisions_total{event_type}`;
- `duplicate_groups_total{size_band}`;
- `duplicate_suppressed_total`;
- `canonical_changes_total{reason}`;
- `processing_stale_leases_total`.

Structured log: `event_id`, `job_id`, `source_id`, `message_id`, `revision_id`, `duplicate_group_id`, `stage`, `outcome`, `duration_ms`, `error_code`.

## 11. Dependencies

- `02-telegram-collector`: persisted envelopes.
- `04-lead-detection`: category/signals for eligible revision.
- `05-lead-scoring`: score for positive category.
- `06-lead-storage`: atomic repositories, WAL и outbox.
- `10-administration-observability`: replay controls, metrics и logs.

## 12. MVP и исключённые функции

MVP включает PROC-001—PROC-018. Исключены fuzzy/semantic similarity, media/OCR, language translation, distributed workers и reprocessing всех исторических versions по расписанию.

## 13. Acceptance criteria и test catalogue

| ID | Requirement | Сценарий | Ожидаемый результат |
|---|---|---|---|
| `AT-PROC-001` | PROC-001 | Два workers claim один envelope | Только один получает lease |
| `AT-PROC-002` | PROC-002 | Сбой между lead и outbox insert | Вся транзакция откатывается |
| `AT-PROC-003` | PROC-003 | CRLF, NFKC variant, zero-width и whitespace fixture | display/dedup/analysis texts совпадают с golden fixture |
| `AT-PROC-004` | PROC-004 | Один fixture обработан дважды | Fingerprints идентичны |
| `AT-PROC-005` | PROC-005 | Replay одного new envelope | Одна message и одна revision |
| `AT-PROC-006` | PROC-006 | Первое непустое сообщение | Создана immutable revision 1 |
| `AT-PROC-007` | PROC-007 | Edit меняет текст | Новая revision, новый processing result |
| `AT-PROC-008` | PROC-008 | Старая edit приходит последней | Current остаётся более новой Telegram edit |
| `AT-PROC-009` | PROC-009 | Удалить canonical | Следующий active member продвигается; повторного notification нет |
| `AT-PROC-010` | PROC-010 | Одинаковый hash через 29 и 31 день | 29 объединён, 31 не объединён |
| `AT-PROC-011` | PROC-011 | Transitive fixtures A-B-C | Одна стабильная group |
| `AT-PROC-012` | PROC-012 | Одинаковое время в трёх sources | Побеждает минимальный source ID/message ID |
| `AT-PROC-013` | PROC-013 | Более ранняя копия приходит backfill | Lead пере привязан; новый lead/outbox отсутствует |
| `AT-PROC-014` | PROC-014 | Non-canonical copy | Detection не вызывается |
| `AT-PROC-015` | PROC-015 | Re-score current revision | Новый immutable result с version IDs |
| `AT-PROC-016` | PROC-016 | Пять transient errors | Точная delay sequence, затем failed |
| `AT-PROC-017` | PROC-017 | Crash после commit до job ack | Replay создаёт ноль дубликатов |
| `AT-PROC-018` | PROC-018 | Manual replay failed job | Один новый result, revision не меняется |

## 14. Принятые записи decision log

- `DEC-PROC-001`: message identity равна `(source_id, telegram_message_id)`.
- `DEC-PROC-002`: exact dedup использует NFKC/casefold SHA-256 и окно 30 дней.
- `DEC-PROC-003`: canonical выбирается по publication time, source ID, Telegram message ID.
- `DEC-PROC-004`: edit создаёт revision и повторный processing result; delete сохраняет последний текст до очистки.
- `DEC-PROC-005`: fuzzy и semantic deduplication отсутствуют в MVP.

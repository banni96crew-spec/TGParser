# Навигация: Message Processing

Owner PRD: `PRD.md`  
Requirement prefix: `PROC`  
Primary responsibility: persisted processing pipeline, нормализация, revisions, edits/deletes и exact deduplication.

## Read first

1. `../../README.md`
2. `../../shared/DOMAIN_MODEL.md`
3. `../../shared/INTEGRATION_CONTRACTS.md`
4. `../02-telegram-collector/PRD.md`
5. `PRD.md`
6. `../04-lead-detection/PRD.md`

## Границы модуля

- Owned entities: `TelegramMessage`, `TelegramMessageRevision`, semantics `ProcessingJob`, `ProcessingResult`, `DuplicateGroup`.
- Consumed contracts: `TelegramEventEnvelope`, active rule-set reference.
- Published contracts: `MessageReadyForDetection`, `MessageDeleted`, `CanonicalMessageChanged`, `ProcessingCompleted`, `ProcessingFailed`.
- Upstream modules: `02-telegram-collector`, `06-lead-storage`.
- Downstream modules: `04-lead-detection`, `05-lead-scoring`, `07-lead-dashboard`, `10-administration-observability`.
- Required acceptance suites: `AT-PROC-*` из `PRD.md`.

## Out of scope

- Telegram API calls.
- Semantic или fuzzy deduplication.
- Категория и score.
- Отправка уведомлений.

## Change checklist

1. Сохранить детерминированные normalization и canonical algorithms.
2. Обновить shared domain/contracts при изменении revision или event.
3. Проверить replay, edit, delete, canonical promotion и crash recovery.
4. Обновить `../../TRACEABILITY.md` для изменённых `PROC-*`.
5. Не переносить rule logic из Lead Detection.

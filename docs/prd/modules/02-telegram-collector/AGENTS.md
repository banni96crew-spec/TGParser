# Навигация: Telegram Collector

Owner PRD: `PRD.md`  
Requirement prefix: `COL`  
Primary responsibility: единая Telegram-интеграция, backfill, live updates, reconciliation и checkpoints.

## Read first

1. `../../README.md`
2. `../../shared/DOMAIN_MODEL.md`
3. `../../shared/INTEGRATION_CONTRACTS.md`
4. `../01-source-discovery/PRD.md`
5. `PRD.md`

## Границы модуля

- Owned entities: `CollectorCheckpoint`, semantics `CollectionJob`, `TelegramEventEnvelope`, `CollectorRuntimeState`.
- Consumed contracts: `SourceMonitoringRequested`, `SourcePaused`, `SourceDisabled`, `TelegramGateway`.
- Published contracts: `TelegramMessageReceived`, `TelegramMessageEdited`, `TelegramMessageDeleted`, `CollectorSourceInaccessible`, `CollectionJobStateChanged`.
- Upstream modules: `01-source-discovery`, `06-lead-storage`, `11-security`, `12-deployment-infrastructure`.
- Downstream modules: `03-message-processing`, `10-administration-observability`.
- Required acceptance suites: `AT-COL-*` из `PRD.md`.

## Out of scope

- Классификация и scoring.
- Source approval.
- Account rotation.
- Обход Telegram API limits.
- Прямые вызовы Telethon вне `TelegramGateway`.

## Change checklist

1. Сохранить Telethon полностью за `TelegramGateway`.
2. Не менять source lifecycle вне команд модуля Source Discovery.
3. Обновить shared contracts при изменении envelope или event.
4. Обновить `../../TRACEABILITY.md` для изменённых `COL-*`.
5. Проверить replay, restart, FloodWait и checkpoint acceptance suites.

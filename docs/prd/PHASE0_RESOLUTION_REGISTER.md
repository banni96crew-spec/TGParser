# Phase 0 Resolution Register

Статус: **closed** — 16.07.2026.  
Нормативные решения: Decision Log **D-039…D-047**.  
Product implementation authorized after freeze + explicit owner approval dated 2026-07-16 (`AGENTS.md`).

| Blocker ID | Decision | Summary | Primary documents |
|---|---|---|---|
| `P0-COL-GATEWAY` | D-039 | Shared `TelegramGateway`: `connect`, `disconnect`, `resolve_public_source`, `validate_source`, `get_recommendations`, `iter_history`, `iter_updates`, `get_message`; `GatewayFloodWait(until)`; envelope `message_new\|message_edited\|message_deleted`; removed `iter_messages`/`register_live_handler` | `shared/INTEGRATION_CONTRACTS.md`, `modules/02-telegram-collector/PRD.md`, `modules/01-source-discovery/PRD.md` |
| `P0-PROC-DEDUPE-CHECKPOINT` | D-040 | Pipeline: claim → revision → normalize → identity dedupe → exact repost canonical → detection → scoring → persist lead/outbox → processing ack; `CollectorCheckpoint` только с envelope TX (COL), не в `PersistProcessingResult` | `shared/INTEGRATION_CONTRACTS.md` §5/§8, `shared/DOMAIN_MODEL.md` ProcessingLog, `modules/03-message-processing/PRD.md`, `modules/02-telegram-collector/PRD.md` |
| `P0-SCR-WEIGHTS-DETA` | D-041 | DET-A: колонки Dimension+Weight; DET-002 schema; `DetectionResult.matched_rules` с weight/dimension/`matched_excerpt`≤120 | `modules/04-lead-detection/PRD.md`, `shared/DOMAIN_MODEL.md`, `shared/INTEGRATION_CONTRACTS.md` §6 |
| `P0-LEAD-BAND` | D-042 | `Lead.band` = `hot\|warm\|cold\|irrelevant`; create только hot/warm/cold; rescore→irrelevant сохраняет Lead | `shared/DOMAIN_MODEL.md`, `modules/05-lead-scoring/PRD.md`, `modules/06-lead-storage/PRD.md` |
| `P0-AT-ALIGNMENT` | D-043 | `AT-STO-NNN` тестирует `STO-NNN` 1:1; `AT-COL-018` → terminal `dead` | `modules/06-lead-storage/PRD.md`, `modules/02-telegram-collector/PRD.md`, `TRACEABILITY.md` |
| `P0-CRITICAL-TAXONOMY` | D-044 | Codes: `collector_stopped`, `telegram_session_unavailable`, `migration_failed`, `integrity_check_failed`; `NotificationOutbox` lead/incident/score nullable; ровно один из lead или incident; без `database_startup_failed` | `modules/10-administration-observability/PRD.md`, `modules/08-notifications/PRD.md`, `shared/DOMAIN_MODEL.md`, `shared/INTEGRATION_CONTRACTS.md` §9 |
| `P0-NOTIFICATION-SECRETS` | D-045 | Env: `TG_API_ID`, `TG_API_HASH`, `TG_BOT_TOKEN`, `TG_NOTIFY_CHAT_ID`; без `TLD_TELEGRAM_BOT_TOKEN` и SQLite chat id secret store | `modules/08-notifications/PRD.md`, `modules/09-operator-settings/PRD.md`, `modules/11-security/PRD.md` |
| `P0-ENUMS-OWNERSHIP` | D-046 | `SettingChange.reason` + `change_source` `ui\|startup_seed\|migration\|system`; `BackupManifest` semantic owner INF / STO primitives; `source_type` `megagroup`; discovery methods; `matched_excerpt` max 120 | `shared/DOMAIN_MODEL.md`, SET/INF/STO/SRC/DET PRDs |
| `P0-SHADOW-OUTBOX` | D-047 | `notifications.delivery_mode` `shadow\|live` (default shadow); shadow/missing secrets → no `hot_lead` outbox; Leads ok; critical OBS emit; critical outbox only live+secrets; no backlog flush | `README.md` §15, SET/NOT/STO/OBS PRDs |

## Verification checklist

- [x] D-039…D-047 присутствуют в `DECISION_LOG.md` со статусом accepted.
- [x] Shared contracts и owner PRDs выровнены под решения.
- [x] Acceptance IDs сохраняют правило 1:1 с requirements.
- [x] Product Python code не создан в рамках Phase 0 freeze.

# Навигация: Source Discovery

Owner PRD: `PRD.md`  
Requirement prefix: `SRC`  
Primary responsibility: обнаружение публичных Telegram-источников, keyword scouting, реестр кандидатов и ручной lifecycle допуска к мониторингу.

## Read first

1. `../../README.md`
2. `../../shared/DOMAIN_MODEL.md`
3. `../../shared/INTEGRATION_CONTRACTS.md`
4. `PRD.md`

## Границы модуля

- Owned entities: `TelegramSource`, `DiscoveryRun`, `DiscoveryRunQuery`, `SourceDiscoveryEvent`, `SourceAlias`, `SourceApprovalEvent`, `KeywordDiscoveryProfile`, `KeywordDiscoveryProfileVersion`, `SourceDiscoveryEvidence`, `SourceOpportunitySnapshot`.
- Consumed contracts: `TelegramGateway` resolve/recommendations/search/linked-discussion methods, сохранённые публичные ссылки, origin публичных forwarded messages, pure DET detect для scouting text, настройки discovery.
- Published contracts: `SourceCandidateDiscovered`, `SourceApproved`, `SourceMonitoringRequested`, `SourcePaused`, `SourceDisabled`, `KeywordDiscoveryRunStarted`, `KeywordDiscoveryRunFinished`, `SourceOpportunityPromoted`.
- Upstream modules: `06-lead-storage`, `09-operator-settings`, `11-security`, `04-lead-detection` (pure detect), `02-telegram-collector` (gateway search ports).
- Downstream modules: `02-telegram-collector`, `07-lead-dashboard`, `10-administration-observability`.
- Required acceptance suites: `AT-SRC-*` из `PRD.md`.

## Out of scope

- Сбор и классификация monitoring-сообщений.
- Автоматическое начало мониторинга.
- Автоматическое присоединение к источникам.
- Создание Lead из scouting-evidence.
- Платный search / Telegram Stars.
- Обход ограничений доступа.

## Change checklist

1. Сохранить единственного владельца source lifecycle в этом модуле.
2. Обновить `../../shared/DOMAIN_MODEL.md` при изменении состояния или идентичности источника / keyword entities.
3. Обновить `../../shared/INTEGRATION_CONTRACTS.md` при изменении события или gateway search ports.
4. Обновить `../../TRACEABILITY.md` для каждого изменённого `SRC-*`.
5. Не добавлять незаполненные решения или требования без числовых лимитов.
6. Не переносить Source Opportunity Score в `SCR` и не смешивать evidence с Collector/Processing/Lead pipeline.

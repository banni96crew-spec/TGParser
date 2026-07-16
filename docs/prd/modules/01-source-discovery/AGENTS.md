# Навигация: Source Discovery

Owner PRD: `PRD.md`  
Requirement prefix: `SRC`  
Primary responsibility: обнаружение публичных Telegram-источников, реестр кандидатов и ручной lifecycle допуска к мониторингу.

## Read first

1. `../../README.md`
2. `../../shared/DOMAIN_MODEL.md`
3. `../../shared/INTEGRATION_CONTRACTS.md`
4. `PRD.md`

## Границы модуля

- Owned entities: `TelegramSource`, `DiscoveryRun`, `SourceDiscoveryEvent`, `SourceAlias`, `SourceApprovalEvent`.
- Consumed contracts: `TelegramGateway.resolve_public_source`, `TelegramGateway.get_recommendations`, сохранённые публичные ссылки, origin публичных forwarded messages, настройки discovery.
- Published contracts: `SourceCandidateDiscovered`, `SourceApproved`, `SourceMonitoringRequested`, `SourcePaused`, `SourceDisabled`.
- Upstream modules: `06-lead-storage`, `09-operator-settings`, `11-security`.
- Downstream modules: `02-telegram-collector`, `07-lead-dashboard`, `10-administration-observability`.
- Required acceptance suites: `AT-SRC-*` из `PRD.md`.

## Out of scope

- Сбор и классификация сообщений.
- Автоматическое начало мониторинга.
- Автоматическое присоединение к источникам.
- Обход ограничений доступа.

## Change checklist

1. Сохранить единственного владельца source lifecycle в этом модуле.
2. Обновить `../../shared/DOMAIN_MODEL.md` при изменении состояния или идентичности источника.
3. Обновить `../../shared/INTEGRATION_CONTRACTS.md` при изменении события.
4. Обновить `../../TRACEABILITY.md` для каждого изменённого `SRC-*`.
5. Не добавлять незаполненные решения или требования без числовых лимитов.

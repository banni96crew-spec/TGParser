# Module navigation — Lead Dashboard

Owner PRD: `PRD.md`

Requirement prefix: `UI`

Primary responsibility: локальный RU-first web UI, Inbox, lead detail и operator actions.

Owned entities: lifecycle semantics `Lead`, `LeadStatusHistory`, `LeadFeedback`, а также Jinja templates, HTMX fragments, view models, UI routes и presentation state.

Consumed contracts: repositories/query services, source commands, score breakdown, settings, health и deliveries.

Published contracts: локальные HTML routes и operator commands в application services.

Upstream modules: `01-source-discovery`, `02-telegram-collector`, `04-lead-detection`, `05-lead-scoring`, `06-lead-storage`, `09-operator-settings`, `10-administration-observability`.

Downstream modules: отсутствуют; UI является adapter boundary.

Required acceptance suites: `AT-UI-*`, CSRF, escaping, export и optimistic concurrency suites.

## Read first

1. `../../README.md`.
2. `../../shared/DOMAIN_MODEL.md`.
3. `../../shared/INTEGRATION_CONTRACTS.md`.
4. `../05-lead-scoring/PRD.md`.
5. `../06-lead-storage/PRD.md`.
6. `PRD.md`.

## Out of scope

- Telegram collection;
- score calculation;
- direct SQL business logic;
- notification delivery;
- remote и multi-user access;
- automatic outreach.

## Change checklist

- сохранить bind `127.0.0.1:8765` и RU-first labels;
- state-changing route должен иметь CSRF и optimistic version;
- не дублировать business validation owning modules;
- обновить route, view model, acceptance test и `../../TRACEABILITY.md` вместе;
- проверить autoescape и CSV formula protection;
- не добавлять send-to-author actions;
- не создавать продуктовый код без отдельной команды.

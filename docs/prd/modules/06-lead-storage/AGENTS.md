# Module navigation — Lead Storage

Owner PRD: `PRD.md`

Requirement prefix: `STO`

Primary responsibility: SQLite schema, transactions, migrations, jobs, outbox, retention и backup/restore.

Owned entities: физические tables, `Job`, `NotificationOutbox`, `SchemaMigration`, storage tombstones.

Consumed contracts: domain entities и events всех функциональных модулей.

Published contracts: repositories, transaction manager, job store, outbox store, backup/restore commands.

Upstream modules: все модули, записывающие состояние.

Downstream modules: `07-lead-dashboard`, `08-notifications`, `10-administration-observability`, `12-deployment-infrastructure`.

Required acceptance suites: `AT-STO-*`, migration, integrity, replay и recovery suites.

## Read first

1. `../../README.md`.
2. `../../shared/DOMAIN_MODEL.md`.
3. `../../shared/INTEGRATION_CONTRACTS.md`.
4. `../../shared/QUALITY_REQUIREMENTS.md`.
5. `PRD.md`.

## Out of scope

- Telegram API calls;
- classification и score algorithms;
- HTML rendering;
- HTTP delivery уведомлений;
- PostgreSQL и external queue.

## Change checklist

- каждое schema изменение оформить Alembic revision;
- сохранить atomic boundary Lead + Score + Outbox;
- проверить replay, rollback и restart recovery;
- обновить retention tests при изменении data class;
- обновить `../../TRACEABILITY.md` для изменённых requirement IDs;
- проверить отсутствие Telegram session в backup paths;
- не дублировать shared contracts в этом файле;
- не создавать продуктовый код без отдельной команды.

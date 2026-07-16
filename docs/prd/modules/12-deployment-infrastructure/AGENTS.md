# Module navigation — Deployment and Infrastructure

Owner PRD: `PRD.md`

Requirement prefix: `INF`

Primary responsibility: Windows runtime, dependency lock, process topology, startup/shutdown, Task Scheduler, paths, migrations, backup/restore и maintenance schedule.

Owned entities: application directory layout, process lock, Task Scheduler definition, `BackupManifest`, maintenance run metadata.

Consumed contracts: security preflight, Alembic migrations, SQLite integrity, persisted jobs, storage retention jobs.

Published contracts: process lifecycle/readiness, backup manifest, maintenance result, runtime paths.

Upstream modules: `11-security` для preflight invariants.

Downstream modules: все runtime-модули; прямые consumers — `02-telegram-collector`, `06-lead-storage`, `09-operator-settings`, `10-administration-observability`.

Required acceptance suites: `INF-INSTALL`, `INF-STARTUP`, `INF-BACKUP`, `INF-RESTORE`, `INF-MAINTENANCE`, `INF-RELEASE`.

Out of scope: Linux/macOS, Docker/cloud, Redis/Celery, внешняя БД, multi-process и horizontal scaling.

Change checklist:

1. Обновить `INF-*` и `AT-INF-*` в `PRD.md`.
2. Проверить clean install, upgrade, restart, backup, restore и integrity suites.
3. Согласовать изменения paths/lifecycle с Security, Storage и Observability.
4. Обновить shared contracts и traceability.
5. Сохранить single-process, loopback-only и session-excluded-from-backup invariants.


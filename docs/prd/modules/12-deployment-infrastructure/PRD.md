# PRD 12 — Deployment and Infrastructure

## 1. Назначение и границы

Модуль определяет воспроизводимый локальный запуск приложения на Windows, topology одного Python-процесса, управление зависимостями, startup/shutdown, Task Scheduler, каталоги данных, migrations, backup и restore.

## 2. Goals и non-goals

### Goals

- Запускать полный MVP одной командой и автоматически после входа пользователя в Windows.
- Восстанавливаться после restart не более чем за 5 минут.
- Обеспечить проверяемые migrations, backup, restore и SQLite integrity checks.
- Не требовать Redis, Celery, Docker или внешнюю БД.

### Non-goals

- Linux/macOS deployment.
- Контейнерная и облачная инфраструктура.
- Горизонтальное масштабирование и account rotation.

## 3. Принятые решения

- Целевая платформа: Windows 10/11 x64.
- Runtime: Python 3.12.x, один процесс с независимыми asyncio services.
- Dependencies: `uv`, `pyproject.toml` и committed lock-файл.
- HTTP: FastAPI + Uvicorn на `127.0.0.1:8765`.
- Database: SQLite + SQLAlchemy 2.x + Alembic + aiosqlite.
- SQLite pragmas: `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`.
- Один логический DB writer и короткие транзакции.
- Background work: persisted job table и внутренние asyncio workers.
- Автозапуск: Windows Task Scheduler при входе текущего пользователя, restart-on-failure.
- Online backup: ежедневно в `03:00 Europe/Moscow`; хранение 7 daily и 4 weekly copies.
- Cleanup: ежедневно в `04:00 Europe/Moscow`.

## 4. Functional requirements

| ID | Требование |
|---|---|
| INF-001 | Проект MUST фиксировать Python `>=3.12,<3.13` и все runtime dependencies в `uv.lock`. |
| INF-002 | Приложение MUST запускаться одним process entrypoint и создавать отдельные asyncio services для web, collector, jobs, outbox, reconciliation и maintenance. |
| INF-003 | Startup order MUST быть: directories → logging → security preflight → SQLite pragmas → migrations → integrity check → settings → jobs recovery → web → TelegramGateway → workers. |
| INF-004 | Ошибка migrations или integrity check MUST блокировать collector и workers и создавать critical system state. |
| INF-005 | Uvicorn MUST слушать только `127.0.0.1:8765`, иметь один worker process и не включать reload в production profile. |
| INF-006 | Application data MUST находиться в `%LOCALAPPDATA%\TelegramLeadDiscovery\` с каталогами `data`, `secrets`, `logs`, `backups`, `exports` и `tmp`. |
| INF-007 | Shutdown MUST прекратить приём новых jobs, остановить Telegram live subscription, дождаться текущих коротких транзакций максимум 30 секунд и закрыть SQLite. |
| INF-008 | Прерванные persisted jobs MUST восстанавливаться по lease timeout 5 минут без дублирования committed результатов. |
| INF-009 | Task Scheduler MUST запускать приложение при входе текущего пользователя, делать до 3 restart attempts с интервалом 1 минута и не запускать второй экземпляр. |
| INF-010 | Process MUST использовать application lock; второй экземпляр завершается с кодом `already_running`. |
| INF-011 | Online SQLite backup MUST запускаться ежедневно в 03:00 и записываться сначала во временный файл. |
| INF-012 | Backup MUST считаться готовым только после `PRAGMA integrity_check = ok`, atomic rename и записи manifest. |
| INF-013 | Retention MUST сохранять 7 последних daily и 4 weekly copies; weekly copy — последняя успешная копия воскресенья. |
| INF-014 | Backup MUST исключать `secrets`, Telegram session, logs, metrics и временные exports. |
| INF-015 | Restore MUST требовать остановленного приложения, проверять выбранную копию, сохранять текущую БД как rollback copy и выполнять post-restore integrity check. |
| INF-016 | При неуспешной pre-restore или post-restore проверке restore MUST блокироваться или откатываться соответственно. |
| INF-017 | Maintenance cleanup MUST запускаться ежедневно в 04:00 и удалять истёкшие данные согласно Storage PRD и CSV-файлы старше 1 часа. |
| INF-018 | Migrations MUST выполняться только Alembic; прямое изменение схемы runtime-кодом запрещено. |
| INF-019 | Release validation MUST включать clean install, upgrade migration, restart recovery, backup restore и SQLite integrity tests. |
| INF-020 | Нормальный startup при исправных локальных зависимостях MUST достигать readiness не более чем за 5 минут. |

## 5. Acceptance criteria

| ID | Проверяемый результат |
|---|---|
| AT-INF-001 | `uv sync --frozen` создаёт окружение из lock-файла без изменения lock. |
| AT-INF-002 | Один process entrypoint запускает web, collector, jobs, outbox, reconciliation и maintenance как отдельные asyncio services. |
| AT-INF-003 | Startup trace подтверждает утверждённый порядок всех шагов от directories до workers. |
| AT-INF-004 | Ошибка migration и отдельно ошибка integrity check не позволяют запустить collector/workers. |
| AT-INF-005 | Process запускает ровно один Uvicorn worker только на `127.0.0.1:8765`, без reload. |
| AT-INF-006 | Все шесть каталогов создаются под `%LOCALAPPDATA%\TelegramLeadDiscovery\` и используются соответствующими сервисами. |
| AT-INF-007 | Graceful shutdown прекращает новые jobs, останавливает live subscription и закрывает SQLite не позднее 30 секунд. |
| AT-INF-008 | Startup recovery возвращает stale persisted job по lease timeout 5 минут без duplicate committed result. |
| AT-INF-009 | Task Scheduler выполняет не более 3 restart attempts с интервалом 1 минута и не создаёт параллельный экземпляр. |
| AT-INF-010 | Второй process завершается как `already_running`, не открывая DB writer или web listener. |
| AT-INF-011 | Backup job запускается в 03:00 и до успешной проверки использует только временный файл. |
| AT-INF-012 | Backup становится ready только после `integrity_check = ok`, atomic rename и записи полного manifest. |
| AT-INF-013 | Retention оставляет 7 последних daily и 4 weekly copies; weekly соответствует последней успешной копии воскресенья. |
| AT-INF-014 | Скан backup не находит `secrets`, Telegram session, logs, metrics или временные exports. |
| AT-INF-015 | Restore запускается только при остановленном приложении, создаёт rollback copy и выполняет обе проверки integrity. |
| AT-INF-016 | Повреждённая копия блокируется до замены active DB; неуспешный post-check восстанавливает rollback copy. |
| AT-INF-017 | Cleanup в 04:00 удаляет CSV старше 1 часа и вызывает утверждённые storage retention jobs. |
| AT-INF-018 | Upgrade изменяет схему только Alembic migration; runtime не выполняет прямой schema DDL. |
| AT-INF-019 | Clean install, upgrade migration, restart recovery, backup restore и integrity test suites проходят без ошибок. |
| AT-INF-020 | При исправных локальных зависимостях приложение достигает readiness не более чем за 5 минут. |

## 6. Входные и выходные контракты

### Входы

- `pyproject.toml`, `uv.lock`, environment и application paths.
- Команды `start`, `stop`, `backup`, `restore`, `integrity-check`, `migrate`.
- Persisted jobs и maintenance schedule.

### Выходы

- Process readiness/liveness.
- `BackupManifest(backup_id, created_at, database_revision, sha256, integrity_result, kind)`.
- `MaintenanceRunResult`.
- Exit codes `0`, `startup_failed`, `already_running`, `migration_failed`, `integrity_failed`.

## 7. Data ownership

Модуль владеет application directory layout, process lock, Task Scheduler definition, backup manifests и maintenance run metadata. Schema и business records принадлежат Storage; session принадлежит TelegramGateway и остаётся в `secrets`.

## 8. Состояния и переходы

- Process: `stopped → starting → ready → stopping → stopped`; startup fault даёт `failed`.
- Backup: `scheduled → writing → verifying → ready`; ошибка даёт `failed`, временный файл удаляется.
- Restore: `requested → precheck → replacing → postcheck → completed`; postcheck failure даёт `rollback → failed`.

## 9. Ошибки, retries и recovery

- Task Scheduler: до 3 restart attempts, интервал 1 минута.
- Backup failure не заменяет последнюю успешную копию и повторяется на следующем ежедневном schedule; оператор может запустить ручную копию.
- Cleanup failure создаёт failed job и один автоматический retry через 30 минут.
- Migration/integrity failure не повторяется автоматически в том же startup.
- Worker crash переводит service в unhealthy; process coordinated shutdown позволяет Task Scheduler выполнить restart.

## 10. Security requirements

- Bind только loopback.
- `secrets` исключён из backup и имеет ограниченный Windows ACL.
- Lock, database и backup paths вычисляются из `%LOCALAPPDATA%`, а не принимаются из web request.
- Restore принимает только файл внутри каталога `backups` с валидным manifest и SHA-256.
- Task Scheduler запускает процесс от текущего интерактивного пользователя без elevated privileges.

## 11. Observability

- Logs: startup step, shutdown step, exit code, migration revision, backup/restore/cleanup result и duration.
- Metrics: `process_uptime_seconds`, `startup_duration_seconds`, `backup_age_seconds`, `backup_duration_seconds`, `maintenance_run_total{job,result}`, `worker_restart_total`.
- Readiness включает migrations, integrity, settings и jobs recovery; Telegram availability отображается отдельным health component.

## 12. Dependencies

- Upstream: Security для preflight и ACL invariants.
- Downstream: Storage, Settings, Collector, Observability и все runtime services.

## 13. MVP и исключённые функции

### MVP

- Windows/uv installation, single-process runtime, Task Scheduler, startup/shutdown, migrations, online backup, restore и cleanup.

### DEFERRED

- Подписанные release artifacts.

### Исключено

- Docker, cloud deployment, Redis, Celery, внешняя БД, несколько process workers и горизонтальное масштабирование.

## 14. Acceptance test catalogue

- `INF-INSTALL`: AT-INF-001, AT-INF-006.
- `INF-STARTUP`: AT-INF-002, AT-INF-003, AT-INF-004, AT-INF-005, AT-INF-007, AT-INF-008, AT-INF-009, AT-INF-010, AT-INF-020.
- `INF-BACKUP`: AT-INF-011, AT-INF-012, AT-INF-013, AT-INF-014.
- `INF-RESTORE`: AT-INF-015, AT-INF-016.
- `INF-MAINTENANCE`: AT-INF-017.
- `INF-RELEASE`: AT-INF-018, AT-INF-019.

## 15. Decision log references

- DEC-001: Python 3.12.x on Windows 10/11 x64.
- DEC-003: single-process async runtime.
- DEC-004: FastAPI/Uvicorn loopback web runtime.
- DEC-005: SQLite/SQLAlchemy/Alembic/aiosqlite storage.
- DEC-009: `uv`, `pyproject.toml` and lock-file dependency management.
- DEC-019: Task Scheduler restart strategy.
- DEC-020: daily and weekly backup strategy.

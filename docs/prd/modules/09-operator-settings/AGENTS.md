# Module navigation — Operator Settings and Local Access

Owner PRD: `PRD.md`

Requirement prefix: `SET`

Primary responsibility: настройки единственного оператора, loopback-доступ и безопасное представление наличия секретов.

Owned entities: `OperatorSetting`, `SettingChange`, вычисляемый `RuntimeSecretPresence`.

Consumed contracts: SQLite transaction, transactional outbox, runtime environment, secret file provider.

Published contracts: `SettingsSnapshot`, `settings.changed.v1`, dependency-check result.

Upstream modules: `06-lead-storage`, `11-security`, `12-deployment-infrastructure`.

Downstream modules: `01-source-discovery`, `02-telegram-collector`, `04-lead-detection`, `05-lead-scoring`, `07-lead-dashboard`, `08-notifications`, `10-administration-observability`.

Required acceptance suites: `SET-LOOPBACK`, `SET-VALIDATION`, `SET-SECRETS`, `SET-RECOVERY`.

Out of scope: multi-user, RBAC, registration, remote access, хранение или редактирование секретов через web UI.

Change checklist:

1. Обновить требования и acceptance criteria в `PRD.md`.
2. При изменении сущностей обновить shared domain model.
3. При изменении snapshot или события обновить shared integration contracts.
4. Обновить traceability для каждого затронутого `SET-*`.
5. Проверить отсутствие секретных значений в API, HTML, logs, metrics и exports.

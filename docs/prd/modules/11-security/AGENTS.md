# Module navigation — Security

Owner PRD: `PRD.md`

Requirement prefix: `SEC`

Primary responsibility: loopback boundary, secret/session protection, file ACL, redaction, CSRF и безопасные backup/export invariants.

Owned entities: вычисляемые `SecurityPreflightResult`, `SecretPresenceSnapshot`; секретные значения в доменной модели отсутствуют.

Consumed contracts: Windows runtime paths, HTTP request metadata, structured events, backup/export manifests.

Published contracts: centralized secret provider, redactor, security preflight и health state.

Upstream modules: `12-deployment-infrastructure`.

Downstream modules: все модули; прямые consumers — `02-telegram-collector`, `06-lead-storage`, `07-lead-dashboard`, `08-notifications`, `09-operator-settings`, `10-administration-observability`.

Required acceptance suites: `SEC-BOUNDARY`, `SEC-SECRETS`, `SEC-OUTPUT`, `SEC-RESTORE`.

Out of scope: remote access, multi-user authorization, хранение secrets/session в SQLite или backup.

Change checklist:

1. Обновить `SEC-*` и `AT-SEC-*` в `PRD.md`.
2. Проверить влияние на каждый consumer secret provider/redactor.
3. Обновить shared contracts и traceability.
4. Выполнить boundary, leakage, ACL, CSRF и restore acceptance suites.
5. Не переносить секретные значения в документацию, fixtures, logs или exports.


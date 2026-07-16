# Module navigation — Administration, Logs and Monitoring

Owner PRD: `PRD.md`

Requirement prefix: `OBS`

Primary responsibility: health, readiness, metrics, structured logs, persisted-job controls и recovery visibility.

Owned entities: `ComponentHealth`, `MetricBucket`, `AdminAction`; `ProcessingLog` потребляется как read contract.

Consumed contracts: module heartbeats, persisted jobs, transactional outbox, settings snapshot, backup/cleanup status.

Published contracts: `SystemHealthSnapshot`, `critical.system_event.v1`, health endpoints, admin action result.

Upstream modules: `06-lead-storage`, `09-operator-settings`, `11-security`, `12-deployment-infrastructure`.

Downstream modules: `07-lead-dashboard`, `08-notifications`; остальные runtime-модули являются наблюдаемыми producers.

Required acceptance suites: `OBS-HEALTH`, `OBS-REDACTION`, `OBS-ADMIN`, `OBS-RETENTION`, `OBS-MVP-METRICS`.

Out of scope: бизнес-логика наблюдаемых модулей, внешний monitoring stack, distributed tracing.

Change checklist:

1. Обновить `PRD.md` и соответствующие `OBS-*`/`AT-OBS-*`.
2. Согласовать новые heartbeat и metric contracts в shared integration contracts.
3. Для нового admin action определить confirmation, idempotency и audit event.
4. Проверить redaction logs/metrics и loopback-only доступ.
5. Обновить traceability и recovery tests.

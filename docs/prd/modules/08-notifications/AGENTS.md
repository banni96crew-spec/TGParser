# Module navigation — Notifications

Owner PRD: `PRD.md`

Requirement prefix: `NOT`

Primary responsibility: transactional outbox consumption и Telegram Bot API delivery одному оператору.

Owned entities: `NotificationDelivery`, notification delivery rules, Telegram rendering и Bot API adapter.

Consumed contracts: `lead_hot_entered`, system incidents, outbox store и notification settings.

Published contracts: delivery status, Telegram message ID, notification metrics и health.

Upstream modules: `05-lead-scoring`, `06-lead-storage`, `09-operator-settings`, `10-administration-observability`, `11-security`.

Downstream modules: `07-lead-dashboard`, `10-administration-observability`.

Required acceptance suites: `AT-NOT-*`, outbox replay, restart recovery и secret scan.

## Read first

1. `../../README.md`.
2. `../../shared/INTEGRATION_CONTRACTS.md`.
3. `../05-lead-scoring/PRD.md`.
4. `../06-lead-storage/PRD.md`.
5. `PRD.md`.

## Out of scope

- lead classification и scoring;
- Telegram source collection;
- automatic replies авторам;
- warm/cold delivery;
- email/SMS/push;
- multi-recipient routing.

## Change checklist

- сохранить hot-only eligibility и один recipient;
- сохранить retry offsets 0/1/5/30/120 минут и максимум пять attempts;
- проверить idempotency и uncertain-delivery path;
- не включать полный text, contacts или secrets;
- синхронно обновить renderer, contract, `AT-NOT-*` и `../../TRACEABILITY.md`;
- не вызывать Bot API внутри Lead transaction;
- не создавать продуктовый код без отдельной команды.

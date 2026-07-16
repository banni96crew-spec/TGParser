# Module navigation — Lead Scoring

Owner PRD: `PRD.md`

Requirement prefix: `SCR`

Primary responsibility: детерминированный score, band, breakdown и re-score.

Owned entities: `LeadScore`, `LeadScoreComponent`, scoring policy в `RuleSetVersion`.

Consumed contracts: `ProcessingResult`, matched rules, `TelegramMessage.published_at`, `TelegramSource.quality_score`.

Published contracts: `ScoreResult`, current lead band, `lead_hot_entered` outbox event.

Upstream modules: `03-message-processing`, `04-lead-detection`, `01-source-discovery`.

Downstream modules: `06-lead-storage`, `07-lead-dashboard`, `08-notifications`, `10-administration-observability`.

Required acceptance suites: `AT-SCR-*`, storage atomicity, outbox replay.

## Read first

1. `../../README.md`.
2. `../../shared/DOMAIN_MODEL.md`.
3. `../../shared/INTEGRATION_CONTRACTS.md`.
4. `../04-lead-detection/PRD.md`.
5. `PRD.md`.

## Out of scope

- поиск сигналов в тексте;
- хранение SQLite schema;
- отображение UI;
- доставка Telegram messages;
- AI/LLM и автоматическая настройка весов.

## Change checklist

- сохранить сумму dimension caps равной 100;
- синхронно обновить formula, bands, contracts и `AT-SCR-*`;
- обновить `../../TRACEABILITY.md` для изменённых requirement IDs;
- проверить переходы в hot и отсутствие повторного alert внутри hot;
- не дублировать shared contracts в этом файле;
- не создавать продуктовый код без отдельной команды.

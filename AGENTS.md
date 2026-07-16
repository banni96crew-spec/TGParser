# Telegram Lead Discovery — навигация для AI-агентов

## Назначение

Этот файл маршрутизирует работу по техническому PRD. Нормативные требования находятся в `docs/prd`, а не в `AGENTS.md`. Продукт предназначен для одного локального оператора. Product implementation is authorized after Phase 0 contract freeze (D-039..D-047) and explicit owner implementation approval dated 2026-07-16; product code MUST follow PRD.

Engineering-governance для качества работы LLM-агентов вынесен в [docs/engineering/README.md](docs/engineering/README.md). Его owner contract регулирует только процесс изменения репозитория, не входит в product PRD/`TRACEABILITY.md`, не разрешает AI/LLM в product runtime и не расширяет допустимый scope задачи. Feature flags и shadow/preventive matrix — в [.cursor/hooks/policy-manifest.json](.cursor/hooks/policy-manifest.json). Локальные evidence claims проверяются независимо (`tools/quality/verify-local-claim.mjs`) и важнее самоотчёта `### Compliance`. Authoritative CI / required merge blocked until [GIT_HOSTING_PREREQUISITE.md](docs/engineering/GIT_HOSTING_PREREQUISITE.md) (`AT-GOV-009`).

## Обязательный порядок чтения

1. `docs/prd/README.md`.
2. `docs/prd/DECISION_LOG.md`.
3. Релевантные документы из `docs/prd/shared`.
4. `AGENTS.md` primary-модуля.
5. `PRD.md` primary-модуля.
6. PRD его непосредственных upstream- и downstream-модулей.
7. `docs/prd/TRACEABILITY.md` перед завершением изменения.

## Иерархия источников истины

1. Зафиксированные ограничения и архитектура master PRD.
2. Принятые записи `DECISION_LOG.md`.
3. Общие domain и integration contracts.
4. PRD модуля-владельца поведения.
5. Ссылки модулей-потребителей.

При расхождении агент обязан привести нижестоящий документ в соответствие с вышестоящим в рамках того же изменения.

## Маршрутизация

| Prefix | Primary module | Когда выбирать |
|---|---|---|
| `SRC` | `01-source-discovery` | кандидаты, graph discovery, source registry, ручное одобрение |
| `COL` | `02-telegram-collector` | Telethon, backfill, live updates, reconciliation, checkpoints |
| `PROC` | `03-message-processing` | normalization, processing orchestration, retries, edits/deletes, dedupe |
| `DET` | `04-lead-detection` | категории, versioned rules, regex, hard exclusions, объяснения |
| `SCR` | `05-lead-scoring` | score components, bands, re-score, calibration |
| `STO` | `06-lead-storage` | SQLite, migrations, repositories, revisions, outbox, очистка |
| `UI` | `07-lead-dashboard` | local web UI, inbox, lead detail, triage, exports |
| `NOT` | `08-notifications` | Bot API, outbox delivery, retry, idempotency |
| `SET` | `09-operator-settings` | single-operator settings и local access |
| `OBS` | `10-administration-observability` | health, metrics, logs, job control, recovery visibility |
| `SEC` | `11-security` | secrets, session, ACL, redaction, local network boundary |
| `INF` | `12-deployment-infrastructure` | runtime, startup, scheduler, backup/restore, Windows deployment |

Если задача затрагивает несколько модулей, primary owner определяется по сущности или поведению, которое изменяется. Потребители контрактов не становятся владельцами контракта.

## Правила изменения PRD

- Любое MVP-требование имеет уникальный ID и приоритет `MUST`.
- Явно исключённая функция маркируется `DEFERRED` и получает точную границу.
- Запрещены незаполненные решения, открытые вопросы и маркеры отсроченного выбора.
- Все лимиты, интервалы, thresholds, retries и состояния задаются конкретно.
- Полное определение сущности, enum, события или DTO существует только у одного владельца.
- Изменение контракта одновременно обновляет owner PRD, shared contract, потребителей и `TRACEABILITY.md`.
- Acceptance test получает ID `AT-<PREFIX>-NNN` и ссылается минимум на одно требование.
- `AGENTS.md` остаётся коротким маршрутизатором и не копирует требования.
- Документация пишется по-русски; идентификаторы, имена сущностей и протоколы — по-английски.

## Проверка перед завершением

- нет дублирующихся requirement и test IDs;
- все локальные ссылки существуют;
- каждое требование имеет проверяемый acceptance criterion;
- каждое межмодульное событие описано в `INTEGRATION_CONTRACTS.md`;
- `TRACEABILITY.md` обновлён;
- продуктовый код не создан и не изменён.

# LLM Assurance Model

| Поле | Значение |
|---|---|
| `schema_version` | `1.1.0` |
| Статус | approved baseline |
| Owner | repository owner |
| Accountable approver | единственный локальный оператор / владелец репозитория |
| Область | engineering governance для LLM-assisted changes |

## 1. Ownership и precedence

Этот документ — owner contract для LLM assurance. Он не является product PRD и не включается в `docs/prd/TRACEABILITY.md`.

При конфликте действует следующий порядок:

1. product hard invariants, master PRD и принятый `DECISION_LOG.md`;
2. явный scope и запреты текущей задачи;
3. этот owner contract;
4. [Change Evidence](CHANGE_EVIDENCE.md) и [LLM Quality Recovery](LLM_QUALITY_RECOVERY.md);
5. capability fixtures и прочие производные записи.

Только единственный локальный оператор / владелец репозитория утверждает новую версию contract и исключения. Исключение обязано быть явным, ограниченным одной задачей и не может отменять product hard invariant.

## 2. Task profiles

Каждая задача до действий получает ровно один `task_profile`:

- `read_only` — разрешает чтение и не изменяет repository, Git/hosting или user-level state;
- `documentation_mutation` — разрешает только явно перечисленные documentation, governance schema и fixture paths;
- `product_mutation` — допускает product code только по отдельному явному approval и product workflow; этот batch его не предоставляет.

Task contract следует [task-contract.schema.json](../../schemas/quality/task-contract.schema.json), перечисляет allowed/forbidden scope, required capabilities и evidence policy. Отсутствие подтверждённой capability не трактуется как разрешение.

## 3. Capability и evidence boundaries

Capability baseline описывает только сведения, подтверждённые текущей repository configuration. Declaration hook key не доказывает runtime invocation или payload shape. Неподтверждённые payloads получают `support_status: unsupported` и `execution_status: not_run`.

Local claim подтверждает только результат локально выполненной проверки. CI claim допустим только при ссылке на реально завершившийся CI run; локальный результат нельзя переименовывать в CI evidence. Evidence claim следует [evidence-claim.schema.json](../../schemas/quality/evidence-claim.schema.json), а journal event — [journal-event.schema.json](../../schemas/quality/journal-event.schema.json).

Capability spike выполняется на Cursor `3.11.25` (`x64`), Node.js `22.22.2` и Windows PowerShell `5.1.19041.6456`. Эти версии описывают локальный evidence baseline, но не заменяют Windows 10/11 smoke matrix.

## 4. Hard boundaries вне нумерации gates

- Product AI/LLM, embeddings и semantic/vector search остаются запрещены master PRD независимо от task profile или local verdict.
- Product hard invariants и `AGENTS.md` имеют precedence над этим contract; затем следуют owner contract, project rules, policy/fixtures и skills/templates.
- Этот local prototype не разрешает Git/hosting, `.github/**`, user-level configuration или product code и не заявляет CI/merge protection.
- `GOV-*` и `AT-GOV-*` принадлежат только engineering governance и не добавляются в product PRD/`TRACEABILITY.md`.

## 5. Требования и acceptance tests

### GOV-001 — Capability fixtures и matrix

Каждый configured или planned hook MUST иметь fixture с подтверждённым уровнем `preventive`, `observational` или `advisory`, stable ID capability и failure behavior. Declaration без runtime evidence остаётся `declared_not_runtime_verified`.

**AT-GOV-001:** capability fixtures и детерминированная matrix существуют; каждый planned hook ссылается на fixture, а неподтверждённый runtime contract блокирует preventive rollout.

### GOV-002 — Task profiles

Task contract MUST содержать `conversation_id`, `task_id`, один profile, allowed/denied paths, owner docs, requirement IDs, required checks и explicit approval. Профили `read_only`, `documentation_mutation`, `product_mutation` имеют разные обязательные фазы.

**AT-GOV-002:** Given/When/Then positive и negative fixtures каждого profile принимают только разрешённые фазы и отклоняют обязательные пропуски.

### GOV-003 — Conversation concurrency и idempotency

Journal MUST быть per-conversation append-only JSONL, использовать SHA-256 filename, bounded exclusive lock и event-specific dedupe только при подтверждённом `stable_instance_id`.

**AT-GOV-003:** 4 concurrent sessions × 100 events и 100 concurrent events одной session дают zero lost/cross-session updates; duplicate со stable ID имеет ровно один effect, а без stable ID не выполняется unsafe dedupe.

### GOV-004 — Deterministic journal degradation

Correctness MUST не зависеть от `sessionStart`; stale lock, interrupted temp, malformed/truncated JSONL и duplicate hooks сохраняют evidence и не вызывают silent reset.

**AT-GOV-004:** delayed `sessionStart`, stale lock, interrupted temp, malformed/truncated journal и duplicate hooks дают документированный deterministic verdict.

### GOV-005 — Preventive bypass denial

Unknown mutation/tool/parser failure MUST давать `deny`; unknown MCP/browser — `ask` или `deny`. `ApplyPatch`, encoded PowerShell и protected product/user/Git scopes не могут получить `allow`.

**AT-GOV-005:** 100 negative bypass cases дают zero разрешённых mutations.

### GOV-006 — Valid profiles и latency

Явно разрешённые actions каждого profile MUST не блокироваться ошибочно; policy decision остаётся pure и bounded.

**AT-GOV-006:** 50 valid fixtures каждого profile дают zero false-positive blocks, а локальный p95 decision latency не превышает `200 ms`.

### GOV-007 — Untrusted evidence claim

Local evidence claim MUST считаться untrusted agent-controlled input и содержать observed hashes и base/head identity только при их фактическом наличии.

**AT-GOV-007:** tampered или stale claim обнаруживается independent recomputation; изменённый claim сам по себе никогда не создаёт `PASS`.

### GOV-008 — Deterministic validators

Governance и PRD validators MUST использовать фиксированные inputs/exclusions, сортировать JSON output и возвращать non-zero для документированных нарушений.

**AT-GOV-008:** повторный запуск каждого validator на одном corpus byte-identical; каждое нарушение даёт deterministic error и non-zero exit.

### GOV-009 — Git prerequisite

CI phase MUST не начинаться без подтверждённых repository root, trusted base SHA, remote, hosting и repository owner required checks.

**AT-GOV-009:** отсутствие любого Git/hosting prerequisite оставляет CI status `not_run` и блокирует CI rollout.

### GOV-010 — CI tampering и stale SHA

Authoritative CI MUST игнорировать local verdict, пересчитывать changed files/hashes из trusted base/head и выявлять outside-Cursor edits.

**AT-GOV-010:** modified source при unchanged claim, modified claim, outside-Cursor edit и stale base SHA всегда дают CI `FAIL`.

### GOV-011 — Hosted/Desktop verdict parity

Hosted Windows checks и Windows 10/11 Desktop smoke MUST воспроизводить одинаковый governance verdict при одинаковых trusted inputs.

**AT-GOV-011:** clean hosted checkout и оба Desktop smoke hosts возвращают одинаковый verdict; hosted run не выдаётся за Desktop compatibility evidence.

### GOV-012 — Transactional installer rollback

Любая отдельно одобренная установка user hooks MUST использовать backup, checksum, deterministic merge и transactional rollback без overwrite неизвестного state.

**AT-GOV-012:** install/upgrade/uninstall восстанавливают byte-identical исходный config; forced failure на каждом шаге оставляет старую либо полностью новую configuration.

### GOV-013 — Per-gate и out-of-band recovery

Каждый gate MUST иметь independent rollback. Operator-only recovery MUST работать без Node, проверять checksum и атомарно восстанавливать known-good project hooks без global fail-open.

**AT-GOV-013:** отключение каждого gate сохраняет остальные; missing Node/corrupt manifest восстанавливаются out-of-band, а автоматический или global fail-open отсутствует.

## 6. Deterministic validator contracts

`validate-governance.mjs` принимает repository root, проверяет owner IDs, schema compatibility, hook-to-capability mapping, inventory и локальные ссылки; output — sorted JSON contract `1.0.0`.

`validate-prd.py` версии contract `1.0.0` читает только `AGENTS.md` и `docs/prd/**/*.md`. Он проверяет уникальные requirement/test definitions, one-to-one mapping, существование canonical `D-NNN`, локальные Markdown links и coverage в `TRACEABILITY.md`. Из анализа исключаются fenced code blocks, engineering governance IDs и внешние URLs. Output — UTF-8 JSON с sorted keys и sorted diagnostics; любое нарушение возвращает exit code `1`.

`validate-capabilities.mjs` сравнивает `.cursor/hooks.json` с capability fixtures и печатает sorted matrix. `validate-journal.mjs` проверяет только явно переданные JSONL paths и не исправляет их.

## 7. Baseline scope

Capability baseline отражает текущие keys `.cursor/hooks.json`, но сам по себе не подтверждает runtime payload contract. Runtime journals, spike artifacts и test temp игнорируются; live `.cursor/session-compliance.json` не читается и не изменяется governance tooling.

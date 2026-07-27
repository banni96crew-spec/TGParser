# Owner binding — execution dispatch override

- **Recorded_at:** 2026-07-27
- **Authority:** product owner instruction (overrides plan multi-role cast density)
- **Does NOT change:** wave goals, acceptance criteria, HC fail-closed gates, ownership file boundaries, Wave 09 live-pilot approval, Wave 10 commit/merge stop
- **Does change:** who is dispatched per wave and whether the coordinator may write

## Rules

| Rule | Why |
|---|---|
| 1 write-agent на wave | Один owner, один контекст, меньше handoff-потерь |
| +1 verifier только на gate | Сохранить HC-4 без каста из 5–7 ролей |
| Architect/critic не в каждой волне | Только Wave 00 и при смене контракта/ADR |
| Security только на 04/05/10 | Не на каждый UI/test slice |
| TDD внутри executor | Отдельный test-engineer почти всегда лишний |
| Главный агент может писать простые волны | HC-0 сейчас artificially inflates cost |

## Practical pattern (updated owner 2026-07-27)

```text
wave = ONE sub-agent (tests + code + gate evidence) → next wave immediately
```

- **Без подтверждения пользователя** между волнами. Координатор сразу стартует следующую при PASS.
- **1 суб-агент на волну** (обычно `executor`). Не кастить отдельный test-engineer/verifier/architect на каждую волну.
- При FAIL/INCOMPLETE — стоп, не переходить к следующей.
- Параллель 03∥04 **не использовать** в этом режиме (строго последовательно, 1 агент).
- **Wave 10**: один агент с ролями code-review + security + release checks в одном dispatch (не 3 отдельных, если не требуется FAIL-retry).
- Wave 09 Part B (live pilot) — по-прежнему только после явного operator approval (HC-6); Part A harness выполняется агентом.
- После Wave 10 — стоп перед commit/push/merge.
- При смене контракта/ADR mid-stream — допустим отдельный docs-агент, затем продолжение.

## Wave 02 status at override time

- Interrupted mid-wave: test-engineer + executor-storage completed; executor-source was interrupted.
- Resume under this override: **one executor** finishes remaining source + any leftover tests/code, then **verifier** gate.
- Do not re-run architect/critic/test-engineer for Wave 02 unless contract/ADR changes.

## Precedence

1. Product MUST/AT and wave AC from the remediation plan + Wave 01 freeze.
2. This dispatch override (agent casting / who writes).
3. Original plan Dispatch lists (informational ownership hints only when override applies).

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

## Practical pattern

```text
wave = todo → executor (tests + code) → verifier
```

- Параллелить только **Wave 03 ∥ Wave 04** при чистом ownership (как в плане).
- **Wave 10** оставить: `code-reviewer` + `security-reviewer` + `verifier` — там это оправдано.
- При смене контракта/ADR: `architect` → `writer` (или executor docs) → `critic` → `verifier` (как Wave 01).
- Security-reviewer: Waves **04, 05, 10** only.

## Wave 02 status at override time

- Interrupted mid-wave: test-engineer + executor-storage completed; executor-source was interrupted.
- Resume under this override: **one executor** finishes remaining source + any leftover tests/code, then **verifier** gate.
- Do not re-run architect/critic/test-engineer for Wave 02 unless contract/ADR changes.

## Precedence

1. Product MUST/AT and wave AC from the remediation plan + Wave 01 freeze.
2. This dispatch override (agent casting / who writes).
3. Original plan Dispatch lists (informational ownership hints only when override applies).

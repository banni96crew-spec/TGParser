# Engineering governance

Этот каталог содержит отдельный от product PRD контур assurance для изменений, выполняемых LLM-агентами.

## Навигация

- [LLM Assurance Model](LLM_ASSURANCE_MODEL.md) — versioned owner contract, требования `GOV-001..GOV-013` и acceptance tests `AT-GOV-001..AT-GOV-013`.
- [Change Evidence](CHANGE_EVIDENCE.md) — правила evidence claims и разделение local/CI evidence.
- [LLM Quality Recovery](LLM_QUALITY_RECOVERY.md) — восстановление после нарушения governance contract.
- [Git hosting prerequisite](GIT_HOSTING_PREREQUISITE.md) — `AT-GOV-009` checklist; authoritative CI blocked until approved.
- [CI observe-only](CI_OBSERVE_ONLY.md) — local recomputation without `.github/workflows`.
- [Windows smoke checklist](WINDOWS_SMOKE_CHECKLIST.md) — Desktop matrix status (`AT-GOV-011`).
- [Quality schemas](../../schemas/quality/) — машиночитаемые контракты task, capability, journal и evidence.
- [Capability baseline](../../tests/fixtures/quality/capabilities/) — подтверждённые declarations текущих hook event keys.
- [Quality tooling](../../tools/quality/) — pure policy/journal libraries, deterministic validators и operator-only recovery.
- [Isolated tests](../../tests/quality/) — Node `node:test` scenarios, работающие только во временных каталогах.
- [Policy manifest](../../.cursor/hooks/policy-manifest.json) — source of truth для feature flags и event matrix.

## Граница

Эти документы управляют только engineering-процессом. Они не изменяют product requirements, domain contracts или `docs/prd/TRACEABILITY.md`. AI/LLM в product runtime остаётся запрещён. Git/hosting operations, user-level configuration и product code не разрешаются самим наличием этого governance-контура.

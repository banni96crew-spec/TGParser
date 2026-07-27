# Wave 01 — rollback (docs-only; do not execute destructive rollback)

- **Wave:** 01 — PRD / contract freeze
- **Captured_at:** 2026-07-27
- **Agent:** verifier
- **HEAD at verification:** `f1b9445`

## Status

Wave 01 changed **documentation only** under `docs/prd/`. No live migrate. No intentional `src/**/*.py` edits.

## Docs restore (note only — DO NOT run unless operator explicitly requests)

Restore Wave 01 PRD paths to HEAD:

```text
git checkout HEAD -- \
  docs/prd/DECISION_LOG.md \
  docs/prd/TRACEABILITY.md \
  docs/prd/modules/01-source-discovery/PRD.md \
  docs/prd/modules/02-telegram-collector/PRD.md \
  docs/prd/modules/03-message-processing/PRD.md \
  docs/prd/modules/04-lead-detection/PRD.md \
  docs/prd/modules/06-lead-storage/PRD.md \
  docs/prd/modules/07-lead-dashboard/PRD.md \
  docs/prd/modules/10-administration-observability/PRD.md \
  docs/prd/modules/12-deployment-infrastructure/PRD.md \
  docs/prd/shared/DOMAIN_MODEL.md \
  docs/prd/shared/INTEGRATION_CONTRACTS.md \
  docs/prd/shared/QUALITY_REQUIREMENTS.md
```

Optional: preserve or remove `.omc/artifacts/lead-discovery-remediation/wave-01/*` separately (orchestration evidence; not product).

## Forbidden

- Do **not** `git reset --hard` (would discard unrelated worktree state / `__pycache__` / plan dirty).
- Do **not** run live DB migrate/downgrade as Wave 01 rollback (no schema applied by this wave).
- Do **not** delete Wave 00 / baseline artifacts.

## Recovery after mistaken checkout

Re-apply writer/revise content from git history or re-dispatch writer using architect-contract-delta + critic-rereview APPROVE closure notes.

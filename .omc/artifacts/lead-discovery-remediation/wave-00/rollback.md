# Wave 00 — rollback

- **Wave:** 00 — baseline и plan ratification
- **Captured_at:** 2026-07-27
- **Agent:** verifier

## Status

**N/A — Wave 00 was read-only on product/docs.**

No product code, migrations, PRD, or live DB changes were made by Wave 00 agents (explorer / planner / architect / critic / verifier).

## What to preserve

- `.omc/artifacts/lead-discovery-remediation/baseline/*`
- `.omc/artifacts/lead-discovery-remediation/wave-00/*` (reports + this evidence kit)
- `.omc/plans/telegram-lead-discovery-remediation.md` (existing dirty orchestration file)

## What not to do

- Do **not** `git reset` / revert / clean `.omc` artifacts to “undo” Wave 00.
- Do **not** run `uv run tld migrate` against the live DB as a rollback or forward action until Wave 09 Part B with operator approval.
- Do **not** delete Critic **APPROVE** or baseline manifests before Wave 01 starts.

## If Wave 00 evidence must be re-run

Re-dispatch verifier only; re-execute §7 commands; overwrite `commands.json` / `verification-report.md` / `acceptance-matrix.md` with a new capture timestamp. Product tree remains untouched.

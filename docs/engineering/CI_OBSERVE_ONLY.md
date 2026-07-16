# CI observe-only recomputation

| Field | Value |
|---|---|
| Tool | `tools/quality/ci-recompute.mjs` |
| Mode | observe-only |
| Authoritative CI | blocked pending [GIT_HOSTING_PREREQUISITE.md](GIT_HOSTING_PREREQUISITE.md) (`AT-GOV-009`) |
| Workflows | **none** — do not create `.github/workflows` from this document |

## Behavior

1. If the workspace is not a Git work tree → `status: not_run`, `at_gov_009: not_run`.
2. If Git exists → recompute changed paths and SHA-256 hashes from the working tree; optionally verify a local claim via `verify-local-claim.mjs` (`--claim=`).
3. Output is sorted JSON. Local claim content is never trusted alone (`AT-GOV-007`).
4. `authoritative_ci` and `required_merge_protection` stay `blocked` until hosting prerequisites and owner approval land.

## Usage

```powershell
node tools/quality/ci-recompute.mjs
node tools/quality/ci-recompute.mjs --claim=.cursor/quality-claims/claim-example.json
```

## Relationship to AT-GOV-010

Full hosted CI tampering detection (`AT-GOV-010`) requires trusted base/head from hosting and an independent runner. Until `AT-GOV-009` is satisfied, treat AT-GOV-010 as `not_run`.

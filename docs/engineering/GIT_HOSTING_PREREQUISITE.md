# Git / hosting prerequisite (AT-GOV-009)

| Field | Value |
|---|---|
| Requirement | `GOV-009` / `AT-GOV-009` |
| Status | `not_run` |
| Authoritative CI | **blocked** pending this checklist |
| Required merge protection | **blocked** pending this checklist |

## Purpose

CI phase and required merge checks must not start without confirmed repository identity, remote, hosting, and owner-required checks. Local observe-only helpers (`tools/quality/ci-recompute.mjs`) may run when a Git work tree exists, but they never become authoritative CI evidence.

## Checklist (all must be confirmed by repository owner)

| Step | Item | Status |
|---|---|---|
| 1 | `git init` completed for this repository (or clone of an existing remote) | pending owner |
| 2 | Trusted remote configured (`git remote -v`) | pending owner |
| 3 | Hosting provider chosen (GitHub / other) and repository created | pending owner |
| 4 | Repository owner / accountable approver recorded | pending owner |
| 5 | Required branch protection / merge checks defined by owner | pending owner |
| 6 | Explicit approval to create `.github/workflows/**` or equivalent hosted CI | **not granted** |

## Explicit approval request

Authoritative CI workflows, required status checks, and merge protection are **out of scope** until the operator/owner replies with an explicit approval that covers:

1. Git hosting provider and repository URL;
2. permission to create hosted CI config (for example `.github/workflows`);
3. which checks are required for merge.

Until that approval exists:

- `AT-GOV-009` remains `not_run`;
- `AT-GOV-010` authoritative CI remains `not_run` / blocked;
- agents must not run `git init`, create remotes, or add `.github/` workflows as part of governance tooling.

## Local observe-only substitute

See [CI_OBSERVE_ONLY.md](CI_OBSERVE_ONLY.md) and `tools/quality/ci-recompute.mjs` for independent local recomputation of diffs/hashes/validators. A local `pass` is not CI evidence.

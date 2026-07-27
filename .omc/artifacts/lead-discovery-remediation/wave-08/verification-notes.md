# Wave 08 — Verification Notes

## Confirmed

- Default discovery results-fragment without `band` hides `weak` and keeps `promising`/`review` (Wave 03 extended, not regressed).
- Funnel counters render from `DiscoveryRun.counters_json` including `pool_exhausted` reason reverse-map and novelty bp/%.
- Opportunity detail shows identity + aliases + provenance + eligibility reasons + score components.
- ReconsiderDismissSuppress POST without confirm → 400; with `RECONSIDER_SUPPRESS` + CSRF → membership removed.
- Sources page exposes reject/reconsider/pause/resume/disable forms (distinct from suppress reconsider).
- `/sources/monitoring` shows checkpoint message id, backlog job count, and error codes for monitoring sources.
- `/health` lists all seven OBS-020 named loops; Jinja avoids reserved `loop` variable.
- Inbox pins active `RuleSetVersion` slug@version + checksum.
- OBS novelty/capacity metrics reject unknown names / forbidden labels.

## Not run

- Live Telegram / browser keyboard-only QA (interactive) — not required for SOLE gate; route HTML assertions cover RU labels and states.
- Full capacity load (Wave 09).

## Security spot-check

- Templates do not print secrets, session files, or raw exception traces.
- CSRF enforced on lifecycle and reconsider-suppress POSTs.
- App bind remains existing loopback configuration (unchanged this wave).

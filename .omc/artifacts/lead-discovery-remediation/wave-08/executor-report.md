# Wave 08 — Executor Report

- **Captured_at:** 2026-07-27T18:20:00+03:00
- **Status:** PASS
- **Wave08_gate:** PASS
- **Dispatch:** EXECUTION_DISPATCH_OVERRIDE (1 agent = tests + code + gate)
- **READY_FOR_WAVE_09:** yes

## Scope delivered

RU-first UI + observability (UI-019..024 / OBS-019..021):

1. Default discovery queue remains `promising,review`; `weak` only via explicit filter (Wave 03 preserved).
2. Run detail funnel: acquired / canonicalized / suppressed / qualified / presented / novel, `pool_exhausted` + reason, `novelty_ratio`.
3. Opportunity card: identity, aliases, provenance, evidence counts, score components, eligibility reasons.
4. `ReconsiderDismissSuppress` UI with CSRF + explicit confirmation (distinct from `ReconsiderSource`).
5. Source lifecycle UI: approve / reject / reconsider / pause / resume / disable.
6. Monitoring coverage page (≤100): checkpoint / backlog / errors.
7. Inbox + lead detail pin active rule version + checksum.
8. Health page lists all INF-022 named loops; empty/loading/error/degraded states visible.
9. OBS-019 novelty/suppress metrics; OBS-020 loop health helpers; OBS-021 capacity metrics.

## Files touched (ownership)

| Path | Responsibility |
|---|---|
| `observability/discovery.py` | OBS-019 novelty/suppress/exhaustion recorders |
| `observability/loops.py` | OBS-020 named loop health |
| `observability/capacity.py` | OBS-021 capacity/latency/recovery metrics |
| `dashboard/discovery_routes.py` | Funnel views, card fields, reconsider-suppress |
| `dashboard/app.py` | Lifecycle routes, monitoring, health loops, rule pin |
| `dashboard/leads.py` | Active rule pin helper |
| `dashboard/templates/*` | RU labels, funnel, card, sources, monitoring, health |
| `dashboard/static/css/app.css` | Lifecycle / funnel layout |
| `source_discovery/service.py` | reject/reconsider/pause/resume/disable |
| `source_discovery/worker.py` | Publish OBS-019 from funnel counters |
| `infrastructure/runtime.py` | Project named loops onto OBS-020 health |
| `tests/integration/test_wave08_ui.py` | AT-UI-019..024 |
| `tests/unit/test_observability_wave08.py` | AT-OBS-019..021 |
| `.omc/artifacts/.../wave-08/*` | Gate evidence |

## Forbidden / not done

- Live Telegram / real credentials in tests
- Secrets / session / raw exceptions in templates
- Non-loopback bind
- commit / push

## Verification

See `commands.json` and `acceptance-matrix.md`.

- focused pytest: **28 passed**
- ruff touched paths: **pass**

## Next

Coordinator may start Wave 09 immediately per override.

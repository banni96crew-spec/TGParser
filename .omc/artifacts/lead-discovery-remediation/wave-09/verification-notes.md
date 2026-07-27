# Wave 09 Part A — Verification Notes

## Confirmed

- Harness uses `monkeypatch.setenv("LOCALAPPDATA", tmp_path)` — never operator live DB.
- FakeTelegramGateway + FlakyBotClient — no real Telegram / Bot API network.
- All Part A scenarios in `harness-report.json` have `"passed": true` and `all_passed: true`.
- Related unit/integration regressions for loader/pipeline: 15 passed.
- Ruff on touched paths: clean.

## Inference

- Burst inject paced at ~40 msg/s (above NFR 10/s) with concurrent drain is a valid compressed wall-clock proof of the 6000-event volume profile; true 10-minute wall schedule was not slept.
- Active ruleset pin cache is safe while a single active RuleSetVersion remains immutable after activation (DET invariant).

## Candidate / residual risk

- Part B live dismiss recurrence / Jaccard / live volume still unproven.
- Live DB still expected on pre-Wave-09 revision until Part B migrate.
- CPU/RAM/disk growth collected only indirectly (wall times); no OS performance counters in harness.

## Part B

Explicitly **NOT_RUN**. Checklist in `part-b-checklist.md`. Do not claim Windows pilot complete.

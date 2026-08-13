# Agent Compliance Hooks

Fail-closed / shadow quality hooks for Telegram Lead Discovery governance.

Owner contract: [docs/engineering/LLM_ASSURANCE_MODEL.md](../../docs/engineering/LLM_ASSURANCE_MODEL.md).
**Source of truth for quality feature flags, event→capability mapping, verified tool IDs, and failure matrix:** [policy-manifest.json](policy-manifest.json).

## Layout

| File | Event | Purpose |
| --- | --- | --- |
| `policy-manifest.json` | — | Feature flags (shadow vs preventive), event matrix, tool IDs |
| `session-start.mjs` | `sessionStart` | Reset `.cursor/session-compliance.json` only (never journals) |
| `mark-sequential-thinking.mjs` | `afterMCPExecution` + `preToolUse` | Set `sequential_thinking_done: true` and increment call evidence |
| `require-preflight.mjs` | `preToolUse` | Block Read/Grep/Glob/Shell/Task/Write until ST done |
| `require-preflight-subagent.mjs` | `subagentStart` | Block subagents until ST done; enforce declared types |
| `quality-*.mjs` | verified shadow events | Observe-only policy/journal via `lib/quality-hook-adapter.mjs` |
| `audit-compliance.mjs` | `stop` | Always `allow`; optional bounded advisory followup (not a hard gate) |
| `lib/compliance-state.mjs` | shared | Session compliance state read/write |
| `lib/policy-manifest.mjs` | shared | Load manifest flags/mapping |
| `lib/quality-hook-adapter.mjs` | shared | Shadow mapping + journal append |
| `test-hooks.mjs` | manual | Runs `tests/quality/hooks.test.mjs` with temp journals only |

## Project hooks (sole enforcement owner)

Loaded from [.cursor/hooks.json](../hooks.json) when this repo is open in Cursor.

State file: `.cursor/session-compliance.json` (gitignored, runtime only).
Journals: `.cursor/quality-journals/` (gitignored).
Claims: `.cursor/quality-claims/` (gitignored, untrusted local claims).

`sessionStart` must not reset or delete conversation journals. Correctness does not depend on `sessionStart` (GOV-004).

`afterTabFileEdit` is **unsupported / unmapped** on Cursor 3.11.25 (not in spike evidence). Do not enable preventive or capture handlers until runtime payload is verified.

## User hooks (separate approval only)

`install-user-hooks.ps1` is **operator-only** and must **not** run automatically.
User-level install requires explicit separate approval (AT-GOV-012). Project hooks remain the sole enforcement owner until that approval exists.

Manual copy (only after approval):

```powershell
# From repo root (PowerShell) — DO NOT run unless explicitly approved
powershell -File .cursor/hooks/install-user-hooks.ps1
```

## Verify hooks loaded

1. Open Cursor **Settings → Hooks** tab — entries should appear.
2. Open **Hooks** output channel after a session starts.
3. Run: `node .cursor/hooks/test-hooks.mjs` (uses isolated temp state; does not corrupt live session-compliance).

## Manual tests

```bash
node .cursor/hooks/test-hooks.mjs
node tools/quality/run-quality-suite.mjs
```

## User playbook

1. **Reject violations:** *«Rejected: no preflight. Retry from sequential-thinking step 1.»*
2. Do not accept diffs or plans without `### Pre-flight` in the first response.
3. Evidence claim + independent `verify-local-claim.mjs` outweigh self-reported `### Compliance` text.
4. Sequential-thinking MCP is mandatory for tool unlock; treat ST as advisory evidence in stop audit, not as sole proof of task quality.

## Rollback

1. Remove or comment out entries in `.cursor/hooks.json` (project).
2. Do not edit `~/.cursor` unless an approved user-hooks install was performed.
3. Set `failClosed: false` only while debugging — not for daily use.
4. Restart Cursor after hooks.json changes.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Hooks not loading | Restart Cursor; check paths in hooks.json |
| False deny after ST | Confirm `afterMCPExecution` matcher `sequentialthinking` fires; `preToolUse` also marks ST as a backup |
| Stop advisory about missing claim | Run evidence checkpoint / write claim under `.cursor/quality-claims/`; stop still allows |
| Hook crash blocks tools | Expected with `failClosed: true` — repair scripts, rerun tests |
| Ask mode blocks MCP | Agent must note in Pre-flight and request Agent mode |

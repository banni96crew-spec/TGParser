# Agent Compliance Hooks

Fail-closed hooks enforcing [00-agent-preflight.mdc](../rules/00-agent-preflight.mdc).

## Layout

| File | Event | Purpose |
| --- | --- | --- |
| `session-start.mjs` | `sessionStart` | Reset `.cursor/session-compliance.json` |
| `mark-sequential-thinking.mjs` | `afterMCPExecution` + `preToolUse` | Set `sequential_thinking_done: true` and increment call evidence |
| `require-preflight.mjs` | `preToolUse` | Block Read/Grep/Glob/Shell/Task/Write until ST done |
| `require-preflight-subagent.mjs` | `subagentStart` | Block subagents until ST done; enforce declared types |
| `audit-compliance.mjs` | `stop` | Post-session compliance followup |
| `lib/compliance-state.mjs` | shared | State read/write utilities |
| `test-hooks.mjs` | manual | Simulate B-T1/B-T2/B-T3 |

## Project hooks (in git)

Loaded from [.cursor/hooks.json](../hooks.json) when this repo is open in Cursor.

State file: `.cursor/session-compliance.json` (gitignored, runtime only).

## User hooks (personal fail-closed)

Copy for enforcement on your machine even if project hooks are disabled:

```powershell
# From repo root (PowerShell)
$dest = "$env:USERPROFILE\.cursor"
New-Item -ItemType Directory -Force -Path "$dest\hooks\lib" | Out-Null
Copy-Item .cursor\hooks.json "$dest\hooks.json"
Copy-Item .cursor\hooks\*.mjs "$dest\hooks\"
Copy-Item .cursor\hooks\lib\*.mjs "$dest\hooks\lib\"
```

Edit `%USERPROFILE%\.cursor\hooks.json` — change commands to:

```json
"command": "node hooks/session-start.mjs"
```

User state file: `%USERPROFILE%\.cursor\session-compliance.json`

## Verify hooks loaded

1. Open Cursor **Settings → Hooks** tab — entries should appear.
2. Open **Hooks** output channel after a session starts.
3. Run manual tests: `node .cursor/hooks/test-hooks.mjs`

## Manual tests (B-T1..B-T4)

```bash
node .cursor/hooks/test-hooks.mjs
```

Expected: deny without ST, allow after ST, mark ST evidence from both hook paths, isolate `sessionStart`, then restore live session state.

## User playbook

1. **Reject violations:** *«Rejected: no preflight. Retry from sequential-thinking step 1.»*
2. Do not accept diffs or plans without `### Pre-flight` in the first response.
3. If agent is stuck on deny, check Hooks output channel and `session-compliance.json`.
4. End of task: require `### Compliance` block per 00-agent-preflight.

## Rollback

1. Remove or comment out entries in `~/.cursor/hooks.json` (user) or `.cursor/hooks.json` (project).
2. Set `failClosed: false` only while debugging — not for daily use.
3. Restart Cursor after hooks.json changes.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Hooks not loading | Restart Cursor; check paths in hooks.json |
| False deny after ST | Confirm `afterMCPExecution` matcher `sequentialthinking` fires; `preToolUse` also marks ST as a backup |
| Stop audit says no ST after tests | Run `node .cursor/hooks/test-hooks.mjs`; it restores `.cursor/session-compliance.json` with ST evidence |
| Hook crash blocks all tools | Expected with `failClosed: true` — repair broken imports in `lib/compliance-state.mjs`, rerun test-hooks |
| Ask mode blocks MCP | Agent must note in Pre-flight and request Agent mode |

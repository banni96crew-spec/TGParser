# Agent Compliance Tests

Manual test prompts for verifying [00-agent-preflight.mdc](00-agent-preflight.mdc) and [hooks](../hooks.json) enforcement.

**Procedure:** new Cursor session → send prompt → check Hooks output channel → verify `### Pre-flight` and `### Compliance` blocks.

## Phase A tests (rules only, before hooks)

| ID | Prompt | Expected |
|----|--------|----------|
| A-T1 | «Где определён `runGateG4`?» | Pre-flight `Complex: no`, then Grep |
| A-T2 | «Добавь hook для preflight» | Pre-flight `Complex: yes`, skills: create-hook, MCP: sequential-thinking |
| A-T3 | «Объясни pipeline.ts» without preflight | User reject: *«Rejected: no preflight. Retry step 1.»* |

## Phase B tests (hooks)

| ID | Action | Expected |
|----|--------|----------|
| B-T1 | New session → `Read` without sequential-thinking | **Deny** with agent_message |
| B-T2 | sequential-thinking → `Read` | **Allow** |
| B-T3 | Broken hook script with `failClosed: true` | **Deny** (not fail-open) |
| B-T4 | Hooks tab shows loaded hooks | pass |
| B-T5 | Restart Cursor after save hooks.json | hooks reloaded |

## Phase C tests (full compliance)

| ID | Prompt | Mode | Complex | Must use | Must block without preflight |
|----|--------|------|---------|----------|------------------------------|
| AC-01 | «Где runGateG4?» | Ask | no | sequential-thinking | Read until ST done |
| AC-02 | «Добавь validate в g4Design» | Agent | yes | gate skill, tests | Write until ST done |
| AC-03 | «План: design assembly» | Plan | yes | premium-website-designer, planner subagent | Task until ST done |
| AC-04 | «Объясни 00-project-overview» | Ask | no | ST only | — |
| AC-05 | User reject test | Agent | yes | retry from ST | hook + user reject |

## User reject template

```
Rejected: no preflight. Retry from sequential-thinking step 1.
```

Do not accept diffs, plans, or answers without `### Pre-flight` in the first response.

## Compliance block (end of task)

```markdown
### Compliance
- sequential-thinking: pass|fail
- preflight-block: pass|fail
- skills-used: [paths] | none
- subagents-used: [ids] | none
- hook-audit: pass|fail|not_run
```

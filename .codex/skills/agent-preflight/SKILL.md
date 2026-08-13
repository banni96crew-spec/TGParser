---
name: agent-preflight
description: Mandatory first workflow for every agent task — sequential-thinking MCP, Pre-flight inventory block, skill/subagent selection before any Read/Grep/Shell/Task. Use at the start of every task in Agent, Plan, or Ask mode; when uncertain about which skills or subagents to use; when implementing complex multi-file work; or when hooks block tools until preflight completes. Do NOT use to skip preflight in Ask mode.
---

# Agent Preflight

Mandatory workflow before any implementation, exploration, or answer that requires tools.

## When to use

- **Every task** — first procedure before other tools.
- **Complex: yes** — always read this skill if inventory is unclear.
- **Hooks blocking tools** — agent must complete Steps 1–3 first.
- User mentions preflight, compliance, sequential-thinking, or `00-agent-preflight`.

**Not for:** skipping preflight because mode is Ask or Plan.

## Related rules

- [00-agent-preflight.mdc](../../rules/00-agent-preflight.mdc) — output contract and complex criteria
- [INVENTORY.md](../INVENTORY.md) — skill trigger reference (Telegram Lead Discovery only)
- [AGENT-COMPLIANCE-TESTS.md](../../rules/AGENT-COMPLIANCE-TESTS.md) — manual test prompts
- [LLM_ASSURANCE_MODEL.md](../../../docs/engineering/LLM_ASSURANCE_MODEL.md) — governance owner contract

Evidence claims verified by `tools/quality/verify-local-claim.mjs` outweigh self-reported `### Compliance` text. Sequential-thinking is required for tool unlock; treat it as advisory for final quality proof.

## Procedure (ordered)

### Step 1 — Sequential thinking

Call MCP `user-sequential-thinking` / `sequentialthinking`:

- **Complex: no** — minimum 1 thought
- **Complex: yes** — 2–3 thoughts (scope, risks, tool inventory)

### Step 2 — Inventory

Determine `Complex: yes|no` per 00-agent-preflight criteria.

If **Complex: yes**, list:

| Category | Source | Action |
|----------|--------|--------|
| Subagents | Task tool roster | Pick `subagent_type` with reason |
| MCPs | Available MCP servers | List server/tool pairs needed |
| Skills | [INVENTORY.md](../INVENTORY.md) | Match task keywords to skill paths |

If **Complex: no**, set all inventory lines to `none — trivial`.

### Step 3 — Print Pre-flight block

```markdown
### Pre-flight
- Mode: Agent|Plan|Ask
- Complex: yes|no
- Reason: <1 sentence>
- Sequential-thinking: done
- Subagents: <id> — <why> | none — <reason>
- MCPs: <server/tool> — <why> | none — <reason>
- Skills: <path/to/SKILL.md> — <why> | none — <reason>
- First action after preflight: <concrete next step>
```

### Step 4 — Read matching skill (Complex: yes only)

If a skill matches in INVENTORY, `Read` its `SKILL.md` before coding or running pipeline commands.

### Step 5 — Proceed

Execute `First action after preflight`. Use only declared subagents for `Task` calls.

### Step 6 — Compliance block (task end)

```markdown
### Compliance
- sequential-thinking: pass|fail
- preflight-block: pass|fail
- skills-used: [paths] | none
- subagents-used: [ids] | none
- hook-audit: pass|fail|not_run
- evidence-claim: pass|fail|not_run
```

Prefer an independently verified evidence claim over this self-report when both exist.

## Complex criteria (quick reference)

**yes:** ≥2 files, gates/orchestrator/steps, new rules/skills, tests+code, plan lists tools  
**no:** single lookup, explain cited code, one-symbol question

## MCP unavailable

If sequential-thinking MCP is blocked in current mode:

1. State in Pre-flight `Reason`
2. Ask user to switch to Agent mode
3. Do not call other tools until resolved or user overrides

## Verification

- [ ] Sequential-thinking MCP called (hooks set `sequential_thinking_done`)
- [ ] Pre-flight block printed before Read/Grep/Shell/Task
- [ ] Matching skills read when Complex: yes
- [ ] Compliance block at task end

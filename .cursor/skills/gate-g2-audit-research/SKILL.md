---
name: gate-g2-audit-research
description: Run Gate G2 code checks after Audit or Research — schema validation, at least 3 findings, and each evidence reference must be verifiable (filesystem paths for Audit; URL, query, or lead.json field for Research). Use this skill when implementing runGateG2 in src/gates/g2Audit.ts, debugging why Copy did not start, or verifying audit.json and research.json before the next stage. Also use for G2 failures, missing evidence, findings count, or has_website vs no_website branch artifacts. Do NOT use for writing audit.json (agent-audit), web research (web-research-company S13), ajv-only checks (validate-contract), or G2 LLM tone-check.
---

# Gate G2 Audit / Research

Quality gate after Audit (`has_website`) or Research (`no_website`) — **code checks only**.

## When to use

- Implementing `runGateG2(ctx): GateResult` in `src/gates/g2Audit.ts` (or `g2AuditResearch.ts`).
- After Audit agent writes `audit.json` or Research agent writes `research.json`.
- Debugging blocked Copy stage — G2 must pass first.
- User asks to verify findings evidence paths exist.

**Not for:** running Audit/Research LLM agents. Not for schema-only validation without findings rules (`validate-contract`). Not for G2 LLM partial (tone, no fabricated numbers). Not for web research procedure (`web-research-company`, S13).

## Related rules

- [03-pipeline-gates.mdc](../../rules/03-pipeline-gates.mdc) — G2 policy, retry 2×, blocks Copy
- [13-gates-code.mdc](../../rules/13-gates-code.mdc) — gate module pattern, read-only
- [21-agent-audit.mdc](../../rules/21-agent-audit.mdc) — audit output shape, evidence requirements
- [20-agent-research.mdc](../../rules/20-agent-research.mdc) — research output shape, G2 on `no_website`

## Prerequisites

- Branch determines input artifact:
  - `has_website` → `leads/{id}/audit.json` (after G1 pass)
  - `no_website` → `leads/{id}/research.json` (after Research stage)
- `validate-contract` / `assertValid` available.
- `src/` may be absent — spec-first.
- Gate module read-only; orchestrator handles retry and `state.json`.

## Procedure

### 1. Resolve input artifact

```typescript
const artifact = branch === 'has_website'
  ? 'audit.json'
  : 'research.json';
const schemaName = branch === 'has_website' ? 'audit' : 'research';
```

### 2. Step 1 — Schema validation (S1)

1. Read `leads/{id}/{artifact}`.
2. `assertValid(data, schemaName)` via `validate-contract`.
3. On fail: return `{ pass: false, gate: 'G2', errors: [...] }` with JSON pointers.

### 3. Step 2 — Findings count

```
data.findings.length >= 3
```

On fail: `lead_id=domeo stage=audit gate=G2 artifact=audit.json findings=2 required>=3`.

### 4. Step 3 — Evidence verification (branch-specific)

For each `finding` in `data.findings`, validate `finding.evidence` per branch.

#### Branch `has_website` (Audit)

Evidence references capture artifacts — **filesystem check**:

1. Strip fragment (`#line`) for path portion.
2. Resolve relative to `leads/{id}/`.
3. Verify file exists on disk (e.g. `capture/desktop.png`, `capture/text.txt`).

#### Branch `no_website` (Research)

Evidence per `20-agent-research` — **not** capture paths. Accept one of:

| Evidence form | Validation |
|---------------|------------|
| `lead.json` or `lead.json#field` | Field exists in `leads/{id}/lead.json` |
| `https://...` URL | Non-empty; optional HEAD/GET 200 if policy requires live source |
| Search query string | Non-empty documented query (no fabricated competitors) |

Do not require `capture/*` paths on Research branch — Capture is skipped.

On fail: `finding id=pos-02 evidence=https://bad.example reason=URL unreachable` or `lead.json#geo field missing`.

### 5. Return GateResult

```typescript
{ pass: true, gate: 'G2', errors: [] }
// or
{ pass: false, gate: 'G2', errors: ['...'] }
```

Diagnostics must include: `lead_id`, `stage`, `gate`, `artifact` path, specific reason.

### 6. G2 LLM partial (out of scope for this skill)

After code checks pass, `03-pipeline-gates` allows optional LLM self-check:

- No fabricated numbers
- Human tone

Implement as agent self-check or thin wrapper in `src/gates/` — **not** in this skill procedure. This skill covers **deterministic** G2 checks only.

### 7. Orchestrator integration

- On `!pass`: retry Audit/Research 2× per `03-pipeline-gates`, then `failed`.
- On code pass + LLM pass (if enabled): `status: done`; Copy may start.
- Copy never runs without G2 pass (`EXAMPLES-leadgenerator`).

## Inputs / Outputs

| Input | Output |
|-------|--------|
| `audit.json` or `research.json` | `GateResult` `gate: 'G2'` |
| `branch` from `state.json` | Selects artifact + schema |

**Code owner (planned):** `src/gates/g2Audit.ts`  
**Stage:** Audit / Research → Gate G2 (before Copy)

## Verification

| Check | Status |
|-------|--------|
| G2 fails when evidence path missing | not run |
| G2 fails when findings < 3 | not run |
| G2 passes on valid PRD-shaped audit | not run |
| Copy blocked until G2 pass | not run |
| `quick_validate.py` | run after write |

## Test prompts

1. «Прогони G2 для leads/domeo/audit.json — проверь что у каждого finding evidence файл существует»
2. «Audit готов, запусти Copy без gate» (must refuse — cite run-pipeline-stage / 03-pipeline-gates)
3. «Перепиши audit.json human tone через gate» (must refuse — LLM partial not this skill)

## Forbidden

- Do not write or rewrite `audit.json` / `research.json` — pipeline agents only.
- Do not run G2 before stage artifact exists.
- Do not skip evidence existence checks.
- Do not implement G2 LLM tone-check in this skill — agent or separate thin wrapper.
- Do not advance to Copy from inside gate module.
- Do not invent evidence paths — only verify what artifact declares.
- Do not use web search here — `web-research-company` (S13) is Research input, not G2.

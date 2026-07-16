---
name: gate-g1-capture
description: Run Gate G1 after Capture — schema via validate-contract, then HTTP 200, screenshot size, and text length checks on capture artifacts. Use this skill when implementing runGateG1 in src/gates/g1Capture.ts, debugging why capture failed G1, or verifying desktop.png/mobile.png and text.txt before Audit starts. Also use for G1 gate failures, screenshot empty or under 5KB, text under 200 chars, or capture retry policy. Do NOT use for ajv-only validation (validate-contract), Playwright capture (capture-website), or running capture again without orchestrator (run-pipeline-stage).
---

# Gate G1 Capture

Quality gate after Capture stage — deterministic tech checks on `capture/*`.

## When to use

- Implementing `runGateG1(ctx): GateResult` in `src/gates/g1Capture.ts`.
- Orchestrator calls gate after `capture-website` completes (`run-pipeline-stage`).
- Debugging why Audit did not start — G1 blocked pipeline.
- User asks why `capture.status: failed` or needs G1 diagnostic messages.

**Not for:** schema registry / `assertValid` implementation alone (`validate-contract`). Not for Playwright capture procedure (`capture-website`). Not for orchestrator retry counting (`run-pipeline-stage`).

## Related rules

- [03-pipeline-gates.mdc](../../rules/03-pipeline-gates.mdc) — G1 policy, retry 2× capture, fail blocks Audit
- [13-gates-code.mdc](../../rules/13-gates-code.mdc) — `g1Capture.ts`, read-only, no Playwright in gate
- [14-capture-step.mdc](../../rules/14-capture-step.mdc) — expected capture outputs

## Prerequisites

- `leads/{lead_id}/capture/` exists after Capture stage.
- `validate-contract` skill / `src/gates/validate.ts` available for schema step.
- `src/` may be absent — spec-first; thresholds from `03-pipeline-gates` / `13-gates-code`.
- Gate module is **read-only** — returns result; orchestrator writes `state.json`.

## Procedure

### 1. Entry point

```typescript
export function runGateG1(ctx: GateContext): GateResult
```

`GateContext` includes `lead_id`, `leadDir`, paths to artifacts. Gate does not mutate files or `state.json`.

### 2. Step 1 — Schema validation (delegate to S1)

1. Read `leads/{id}/capture/meta.json`.
2. Call `assertValid(meta, 'capture-meta')` via `validate-contract` / `validate.ts`.
3. On schema fail: return `{ pass: false, gate: 'G1', errors: [...] }` immediately with JSON paths.

Schema checks are **not** duplicated here — `validate-contract` owns ajv.

### 3. Step 2 — HTTP status

From `meta.json`:

```
meta.http_status === 200
```

On fail: error like `lead_id=domeo stage=capture gate=G1 artifact=capture/meta.json http_status=403`.

### 4. Step 3 — Screenshots (filesystem only)

For each path in `meta.screenshots` (`desktop`, `mobile`):

| Check | Threshold |
|-------|-----------|
| File exists under `leads/{id}/` | required |
| File size | > 5120 bytes (5 KB) |
| Dimensions | width > 0, height > 0 (via image header parse or sharp — no Playwright) |

Paths from meta are relative (e.g. `capture/desktop.png`).

On fail: include artifact path and measured size in `errors[]`.

### 5. Step 4 — Extracted text length

1. Resolve `meta.extracted_text` path (e.g. `capture/text.txt`).
2. Read file; count characters (UTF-8).
3. Require length ≥ 200 characters.

On fail: `capture/text.txt length=87 required>=200`.

### 6. Return GateResult

On all pass:

```typescript
{ pass: true, gate: 'G1', errors: [] }
```

On fail:

```typescript
{
  pass: false,
  gate: 'G1',
  errors: [
    'lead_id=domeo stage=capture gate=G1 artifact=capture/desktop.png reason=size 1024 bytes < 5120'
  ]
}
```

### 7. Orchestrator integration

Per `run-pipeline-stage` / `03-pipeline-gates`:

- On `!pass`: orchestrator retries Capture **2×**, then `capture.status: failed`, `error` in `state.json`.
- On `pass`: orchestrator sets `capture.status: done`, `artifact`, `hash`, `cost: 0`.
- Audit does **not** start until G1 passes.

## Inputs / Outputs

| Input | Output |
|-------|--------|
| `capture/meta.json`, `capture/*.png`, `capture/text.txt` | `GateResult` with `pass`, `gate: 'G1'`, `errors[]` |
| Invalid/missing artifacts | `pass: false` with path-qualified reasons |

**Code owner (planned):** `src/gates/g1Capture.ts`  
**Stage:** Capture → Gate G1 (before Audit)

## Verification

| Check | Status |
|-------|--------|
| G1 passes on valid Foundation capture | not run |
| G1 fails on empty screenshot / short text | not run |
| No Playwright import in `g1Capture.ts` | not run |
| Schema step calls `assertValid` before tech checks | not run |
| `quick_validate.py` on this skill | run after write |

## Test prompts

1. «Реализуй runGateG1 — сначала assertValid meta, потом проверь desktop.png > 5KB и text.txt >= 200 символов»
2. «Capture прошёл, но Audit не стартует — прогони G1 для leads/domeo»
3. «Добавь Playwright в g1Capture чтобы перепроверить скрины» (must refuse — filesystem only)

## Forbidden

- Do not import Playwright in `src/gates/g1Capture.ts` (`13-gates-code`).
- Do not weaken thresholds (5 KB, 200 chars) without PRD update.
- Do not skip schema validation before tech checks.
- Do not mutate capture artifacts or `state.json` inside gate module.
- Do not advance pipeline or set `status: done` from gate — orchestrator only.
- Do not duplicate full `validate-contract` procedure — call `assertValid`.
- Do not run Playwright capture here — `capture-website`.

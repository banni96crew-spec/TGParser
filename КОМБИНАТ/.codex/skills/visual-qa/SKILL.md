---
name: visual-qa
description: Reproducible visual, responsive, and interaction QA for the КОМБИНАТ website pipeline. Use after Frontend Builder completes a task and a production-like build is available. Produces classified findings with evidence for Critic report and G5 gate. Read-only for product code. Do not use to implement fixes or redefine P0-P3 priorities.
---

# Visual QA

## Purpose

Run reproducible visual, responsive, and interaction quality assurance against approved baselines and acceptance criteria.

**Role:** QA Critic workflow (read-only).  
**Priority semantics:** `docs/standards/quality-gates.md` — reference P0–P3; never redefine here.  
**Viewport matrix:** `docs/standards/browser-matrix.md` — reference full matrix; do not duplicate tables in findings.

## When to use

Use when:

- Builder result exists for the task under review
- Production build (`npm run build` + `next start` or task-declared URL) is available
- Baselines, design direction, design system, motion spec, and acceptance criteria are frozen (post G4)

Do **not** use when:

- You are implementing code fixes (hand off to Frontend Builder)
- G1–G4 artifacts are missing or still in flux
- You need to invent new product requirements not in approved docs

## Required inputs

| Input | Source |
|---|---|
| Task contract & Builder result | `docs/templates/builder-task.md`, `docs/templates/builder-result.md` |
| Baselines / acceptance | Task criteria, design system, motion spec, screenshots in `qa/runs/` |
| Browser matrix | `docs/standards/browser-matrix.md` |
| Quality gates | `docs/standards/quality-gates.md` |
| A11y thresholds | `docs/standards/accessibility-standard.md` |
| Performance budgets | `docs/standards/performance-budgets.md` |
| Finding schema | `references/finding-schema.md` |
| Review techniques | `references/review-techniques.md` |

## Algorithm

Execute in order.

### 1. Load baseline and acceptance

1. Read Builder task acceptance criteria, required viewports/states, and frozen decisions.
2. Load approved visual references (design direction, design system, prior accepted screenshots).
3. Note explicit pass/fail thresholds; map defects to P0–P3 using `quality-gates.md` only.

### 2. Production-like build

1. Confirm build matches reviewed commit (hash in Critic report header).
2. Serve production build — not dev server — unless task explicitly waives.
3. Clean storage / hard reload before first capture (see `browser-matrix.md` scenario summary).

### 3. Route × viewport matrix

1. Enumerate routes in scope from Builder task / G4 inventory.
2. Cross with minimum stage viewports: `320`, `375`, `768`, `1440`.
3. Add matrix classes from `browser-matrix.md` when task requires full gate (narrow mobile through wide desktop).
4. Probe breakpoint edges `319`, `767`, `1023` when layout breakpoints exist.

### 4. Screenshots

1. Capture full-page or section crops consistently named: `{task-id}/{route}/{viewport}-{state}.png`
2. Store under `qa/runs/<task-id>/`
3. Compare against baseline or design principles; record diffs in findings

### 5. Interaction states

Per route and component class, exercise:

- Default, hover, focus-visible, active, disabled
- Loading, empty, success, error where implemented
- Open/close for modals, menus, accordions

### 6. Keyboard and zoom

- Tab through full page; verify order, visibility, no traps
- Activate primary CTAs and forms via keyboard
- Zoom 200%; confirm functionality and no critical clipping (`accessibility-standard.md`)

### 7. Reduced motion

- Enable `prefers-reduced-motion: reduce`
- Confirm non-essential motion stops or substitutes; meaning preserved

### 8. Console, network, a11y

- Console: unexpected errors = 0 on happy path
- Network: failed requests = 0 on happy path (`performance-budgets.md`)
- Run axe (or project-declared tool); map to `accessibility-standard.md`
- Lighthouse: median of 3 runs when G5 performance gate applies

### 9. Classify findings

1. Log each defect using `references/finding-schema.md` (all fields required).
2. Assign Priority per `quality-gates.md` definitions.
3. Set Owner (usually `Builder` for code defects, `Art Director` for spec gaps with decision record).
4. Link Source requirement to task ID, design-system rule, or standard section — not personal preference.

### 10. Retest subset

After Builder fixes:

1. Re-run only affected route × viewport × state combinations.
2. Update finding Status; close with evidence path.
3. Re-evaluate gate: `P0=0`, `P1=0`, P2 closed or waived per `quality-gates.md`.

## Outputs

| Output | Location |
|---|---|
| Critic report | Filled `docs/templates/critic-report.md` under `qa/runs/<task-id>/` |
| Findings | Same report; one block per finding per schema |
| Evidence | Screenshots, axe JSON, Lighthouse reports, HAR notes under `qa/runs/<task-id>/` |
| Waivers | P2 waivers via `docs/templates/waiver.md` → `qa/waivers.md` |

## Gate interaction

| Finding priority | Effect |
|---|---|
| P0 | Block all gates; stop release |
| P1 | Block release (G5) |
| P2 | Fix or written waiver within 3 iterations |
| P3 | Backlog; does not hold gate |

Full definitions: `docs/standards/quality-gates.md`.

## Hard limits

- Read-only for `src/`, `public/`, tests — no product code edits
- Every mandatory finding includes evidence + acceptance test reference
- Do not expand scope as QA preferences after G1–G4 freeze
- Write reports only under `КОМБИНАТ` (`qa/`, `docs/`)

## Progressive disclosure

- Finding field definitions and example → `references/finding-schema.md`
- Capture and comparison techniques → `references/review-techniques.md`

## Related agents

- Upstream: Frontend Builder
- Codex agent alias: `.codex/agents/qa-critic.toml`

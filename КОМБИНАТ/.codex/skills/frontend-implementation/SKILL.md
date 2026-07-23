---
name: frontend-implementation
description: Safely implement approved frontend scope after design-system and G4 are accepted. Use when a frozen Builder task contract exists, G3 design system and G4 implementation plan are marked accepted, and production code changes in the КОМБИНАТ worktree are required. Do not use before G4 exit, for strategy/IA changes, or for QA-only review passes.
---

# Frontend Implementation

## Purpose

Implement approved frontend scope in the КОМБИНАТ commercial website pipeline without unauthorized product, IA, token, or acceptance changes.

**Entry gate:** G3 (design system + tokens + motion) and G4 (file-level plan + route inventory) accepted.  
**Exit gate:** Builder result complete; handoff ready for QA Critic.  
**Priority semantics:** see `docs/standards/quality-gates.md` — do not redefine P0–P3 here.

## When to use

Use when:

- `docs/templates/builder-task.md` instance exists with frozen scope and acceptance criteria
- G4 is marked accepted in the current task contract
- Approved inputs exist: brief, IA, `design-direction.md`, `design-system.md`, `motion-spec.md`
- You are the assigned Frontend Builder (sole writer of the main worktree)

Do **not** use when:

- G0–G3 are incomplete or contested
- The task is visual QA, strategy, or design direction only
- You need to change offer, IA, tokens, motion rules, or acceptance without a decision record

## Required inputs

| Artifact | Path / template |
|---|---|
| Task contract | `docs/templates/builder-task.md` (filled instance) |
| Brief & frozen decisions | `docs/project/brief.md`, task `Frozen decisions` |
| Design system | `docs/project/design-system.md` |
| Motion spec | `docs/project/motion-spec.md` |
| Standards (reference only) | `docs/standards/accessibility-standard.md`, `docs/standards/performance-budgets.md`, `docs/standards/browser-matrix.md` |
| Component contract | `references/component-contract.md` (this skill) |
| Implementation checklist | `references/implementation-checklist.md` (this skill) |

Load standards by path; do not copy their thresholds into this skill.

## Algorithm

Execute in order. Do not skip steps.

### 1. Read instructions and scope

1. Read the filled Builder task: goal, in/out scope, files to change, forbidden changes, acceptance criteria, required viewports and states.
2. Read frozen decisions and `docs/project/decision-log.md` for constraints that override defaults.
3. Confirm G3 and G4 acceptance before editing production files.

### 2. Audit architecture and scripts

1. Inspect existing App Router structure, shared components, Tailwind config, and form adapters.
2. Read `package.json` scripts and CI workflow for declared lint, typecheck, test, and build commands.
3. Identify reuse targets; avoid parallel patterns or new dependencies without decision-log approval.

### 3. File-level plan

1. Map each acceptance requirement to concrete files (create / modify / do-not-touch).
2. Confirm the plan matches the G4 route inventory; flag drift before coding.
3. Prefer the smallest vertical slice that proves the contract end-to-end.

### 4. Minimal vertical slice

1. Implement one complete user-visible path first (e.g. hero section on home route).
2. Wire types, server/client boundaries, and data flow before spreading the same pattern.
3. Do not batch unrelated routes before the slice passes local checks.

### 5. States and semantics

1. Implement required UI states: default, hover, focus-visible, active, disabled, loading, empty, success, error.
2. Use semantic HTML, landmarks, heading order, labels, and alt policy per `accessibility-standard.md`.
3. Map decorative vs informative images explicitly.

### 6. Mobile-first responsive

1. Author base styles for narrow mobile first.
2. Add breakpoints upward; probe `319`, `767`, `1023` near grid transitions per `browser-matrix.md`.
3. Verify no horizontal scroll on minimum stage viewports: `320`, `375`, `768`, `1440`.

### 7. Motion (motion-spec only)

1. Add Framer Motion or CSS motion only where `motion-spec.md` defines it.
2. Honor `prefers-reduced-motion`: stop or replace non-essential motion; preserve meaning.
3. Do not invent animation curves, durations, or triggers not in the spec.

### 8. Run checks

Run every command listed in the Builder task `Команды проверки`. At minimum when not overridden:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Capture results honestly. Do not hide failing checks.

### 9. Builder report

Fill `docs/templates/builder-result.md` under the task run folder:

- Changed files and implemented requirements
- Verified states and viewports
- Command results and browser evidence paths
- Known limits and Critic handoff questions

### 10. Critic fixes

When QA Critic returns findings:

1. Fix only in-scope items with proven defects.
2. Do not reinterpret acceptance or expand scope to close P3 backlog items unless tasked.
3. Re-run affected checks and update Builder result; request Critic retest subset.

## Worked example: hero then grid replication

**Goal:** Ship home hero per approved design system.

1. **Slice:** Implement hero at `360×800` and `1440×900` first — layout, typography, CTA, focus, reduced motion.
2. **Prove:** Types compile; no console errors; Lighthouse/a11y spot-check on `/`.
3. **Replicate:** Extract shared section shell and apply the same contract to the next grid block (features, proof, etc.).
4. **Expand viewports:** Cover minimum stage set `320`, `375`, `768`, `1440` before marking section done.
5. **Report:** List hero + one replicated section in Builder result with screenshot paths under `qa/runs/`.

## Hard limits

- Write production code **only** inside `КОМБИНАТ` (`src/`, `public/`, tests, authorized scripts).
- No lorem ipsum; use final or explicitly marked draft content.
- New production dependencies require rationale + approval in `docs/project/decision-log.md`.
- Do not change offer, IA, brand tokens, motion rules, or acceptance without a decision record.
- Do not claim completion with open P0/P1 findings (`quality-gates.md`).

## Outputs

| Output | Location |
|---|---|
| Code changes | Main worktree under `КОМБИНАТ` |
| Builder result | Filled `docs/templates/builder-result.md` instance |
| Browser evidence | `qa/runs/<task-id>/` |
| Waivers (if any) | `qa/waivers.md` via approved template |

## Progressive disclosure

- Component API and file ownership rules → `references/component-contract.md`
- Pre-handoff checklist → `references/implementation-checklist.md`

## Related agents

- Upstream: Art Director (G2–G3), Strategist (G1)
- Downstream: QA Critic (read-only review)
- Codex agent alias: `.codex/agents/frontend-builder.toml`

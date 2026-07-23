# Mission

Build a premium commercial website with a clear offer, coherent visual system,
maintainable frontend, and verified conversion path.

## Sources of truth

- Read `docs/project/brief.md`, approved strategy, design direction, and current task contract before changing code.
- Record architectural or product deviations in `docs/project/decision-log.md`.
- Do not start implementation until the required stage gate is marked accepted.

## Workflow

- Use Strategist → Art Director → Frontend Builder → QA Critic.
- Keep Strategist, Art Director, and QA review read-only; only the assigned Builder may edit the main worktree.
- Do not accept a Builder’s self-review as final QA.
- Do not proceed while P0 or P1 findings remain open.

## Product and design rules

- Use Next.js, TypeScript, Tailwind CSS, and Framer Motion.
- Keep one grid, typography system, spacing system, and visual direction.
- Work mobile-first and use final or explicitly marked draft content; never use lorem ipsum.
- Avoid generic AI section patterns and unsupported claims.
- Implement required hover, focus, active, disabled, loading, empty, success, and error states.

## Engineering rules

- Prefer existing architecture and the minimum number of dependencies.
- Adding a production dependency requires an explicit rationale and approval.
- Preserve accessibility, performance budgets, semantic HTML, and reduced-motion behavior.
- Do not claim completion without browser QA at the required viewports.

## Verification

- After source changes, run the project-declared lint, typecheck, relevant tests, and production build.
- Save browser, accessibility, console, network, and Lighthouse evidence under `qa/runs/`.
- Record accepted compromises in `qa/waivers.md`.

## Workspace

- All project files for this system live in this repository root (`КОМБИНАТ`).
- Canonical skills: `.agents/skills`. Optional alias: `.codex/skills` junction only.
- Standards: `docs/standards/`. Do not duplicate them inside skills.

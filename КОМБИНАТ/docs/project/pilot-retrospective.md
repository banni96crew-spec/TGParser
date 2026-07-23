# Pilot retrospective

Date: 2026-07-17  
Owner: Codex-root

## What worked

- Documents-first G0–G4 produced an unambiguous Builder contract.
- Single-writer frontend under КОМБИНАТ avoided product mix with Telegram Lead Discovery.
- Skills stayed short; standards owned P0–P3 / budgets.

## Friction

- Windows file lock: Cursor process held `tailwindcss-oxide` native module, blocking `npm install` cleanup in-place. Mitigated via ASCII install path `C:\kombinat-fresh` + robocopy, and Tailwind v3 instead of v4 oxide.
- Framer Motion major mismatch with `motion-dom` required pin to 11.18.2.
- ESLint defaulted to linting `node_modules` until ignores added.
- Block comment `*/` inside `qa/runs/*/…` broke an ESM script.

## v2 changes (only observed issues)

1. Prefer Tailwind v3 (or ensure Cursor does not load oxide during install) — recorded D-013.
2. Add eslint `ignores` in scaffold template.
3. Ban `*/` sequences inside block comments in scripts.
4. Consider Playwright only after explicit dependency approval.
5. Upgrade Next.js past 15.5.2 for CVE-2025-66478 in next maintenance pass.

## Metrics (approximate)

- Critic iterations on stage: 1 (within limit of 3)
- Open P0/P1 at release: 0
- Unplanned production dependencies: none beyond planned stack

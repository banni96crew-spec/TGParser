# Implementation plan — AegisOps

**Gate G4:** accepted 2026-07-17

## Stack (pinned at scaffold)

- Next.js App Router + `src/`
- TypeScript
- Tailwind CSS
- Framer Motion
- npm

## File-level plan

1. Scaffold Next.js configs + `src/app` skeleton
2. `src/styles/tokens.css` + `globals.css`
3. `src/components/ui/*` primitives (Button, Input)
4. `src/components/sections/hero.tsx` vertical slice
5. Remaining sections per IA order
6. Mock form adapter `src/lib/forms/mock.ts`
7. `robots.ts`, `sitemap.ts`, `not-found.tsx`
8. Tests + QA scripts + CI

## Frozen decisions

D-001…D-012 in decision-log; G0–G4 docs above.

## Out of scope

CMS, auth, real backend, analytics, legal pages, i18n.

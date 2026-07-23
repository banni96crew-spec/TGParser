# Assumptions

Owner: Codex-root  
Updated: 2026-07-17  
Status: accepted for pilot (owner-confirmed via execute approval)

| ID | Assumption | Decision / TBD | Owner | Deadline |
|---|---|---|---|---|
| A-01 | Next.js App Router with `src/` directory | Accepted | Codex | 2026-07-17 |
| A-02 | Example commands use `npm`; package manager follows lockfile | Accepted: npm + `package-lock.json` | Codex | 2026-07-17 |
| A-03 | First version is one commercial landing page; no CMS, auth, or account area | Accepted | Product Owner | 2026-07-17 |
| A-04 | Forms use mock adapter on pilot | Accepted: mock adapter under `src/lib/forms` | Builder | 2026-07-17 |
| A-05 | Pilot language is single-locale (English for AegisOps demo); no i18n | Accepted: `en` | Strategist | 2026-07-17 |
| A-06 | CI is GitHub Actions | Accepted: `.github/workflows/quality.yml` | Builder | 2026-07-17 |
| A-07 | References and brand materials may be used legally when provided | Accepted for synthetic pilot references | Product Owner | 2026-07-17 |
| A-08 | Lighthouse runs against production build, not dev server | Accepted | QA | 2026-07-17 |
| A-09 | Pilot copy is demonstrative; no fake testimonials, client logos, or unverified metrics | Accepted | Strategist | 2026-07-17 |
| A-10 | Next.js / Tailwind / Framer Motion versions pinned at scaffold time | Accepted at step-14 | Builder | 2026-07-17 |
| A-11 | Analytics, cookie consent, legal pages deferred until market/jurisdiction clarified | Accepted: out of pilot scope | Product Owner | 2026-07-17 |
| A-12 | Canonical skill path is `.agents/skills`; `.codex/skills` optional junction only | Accepted | Codex | 2026-07-17 |
| A-13 | Single writer on main worktree (Frontend Builder) | Accepted | Codex | 2026-07-17 |
| A-14 | Workspace root for all artifacts is `КОМБИНАТ` only | Accepted | Codex | 2026-07-17 |
| A-15 | Deploy target for pilot is local `next start` on loopback | Accepted | Builder | 2026-07-17 |

## Critical TBD remaining

None blocking agents/skills creation. Stack versions resolved at Next.js baseline (step-14).

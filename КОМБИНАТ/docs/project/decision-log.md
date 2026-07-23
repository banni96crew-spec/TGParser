# Decision Log

| ID | Date | Decision | Argument | Alternatives rejected | Owner |
|---|---|---|---|---|---|
| D-001 | 2026-07-17 | Canonical skills live in `.agents/skills` | Codex auto-discovery | Second copy in `.codex/skills` | Codex |
| D-002 | 2026-07-17 | `.codex/skills` may be a junction/symlink alias only | Compatibility without duplication | Duplicate skill trees | Codex |
| D-003 | 2026-07-17 | Codex-root owns gates and merge of agent outputs | Single arbiter | Agents self-advance gates | Codex |
| D-004 | 2026-07-17 | Only Frontend Builder writes main worktree product code | Avoid write races | Parallel builders on same tree | Codex |
| D-005 | 2026-07-17 | Strategist / Art Director / QA Critic are read-only for product code | Decisions and reports, not silent edits | Allow isolated writes without contracts | Codex |
| D-006 | 2026-07-17 | Documents are source of truth across sessions | Prevent context rot | Chat-only decisions | Codex |
| D-007 | 2026-07-17 | Max three ordinary QA iterations per stage | Bound polish loops | Unlimited QA | Codex |
| D-008 | 2026-07-17 | Automated metrics and expert critique stay separate | Lighthouse ≠ composition; Critic ≠ typecheck | Single subjective status | Codex |
| D-009 | 2026-07-17 | Package manager policy: npm | Matches plan examples and lockfile convention | pnpm/yarn until lockfile says otherwise | Codex |
| D-010 | 2026-07-17 | CI: GitHub Actions | Default in plan | Other CI only changes automation layer | Codex |
| D-011 | 2026-07-17 | All implementation writes confined to `КОМБИНАТ` | Isolation from Telegram Lead Discovery | Mixing into parent repo product tree | Codex |
| D-012 | 2026-07-17 | Execute approval authorizes Next.js baseline (step-14) | User requested full plan execution | Wait for a second explicit scaffold permission | Product Owner / Codex |
| D-013 | 2026-07-17 | Use Tailwind CSS v3 for pilot (not v4 oxide) | Cursor held oxide `.node` lock on Windows, blocking clean installs | Tailwind v4 `@tailwindcss/postcss` | Builder / Codex |
| D-014 | 2026-07-17 | Pin `framer-motion@11.18.2` | Avoid motion-dom export mismatch breaking build | framer-motion v12 with mismatched motion-dom | Builder |

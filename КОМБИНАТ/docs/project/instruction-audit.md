# Instruction audit — rule → single source

| Rule | Single source | Must not duplicate in |
|---|---|---|
| Mission / stack / write policy | `AGENTS.md` | skills (except brief mention) |
| P0–P3 + G0–G5 | `docs/standards/quality-gates.md` | skills, agents |
| Viewports / scenarios | `docs/standards/browser-matrix.md` | skills |
| A11y thresholds | `docs/standards/accessibility-standard.md` | skills |
| Perf / Lighthouse budgets | `docs/standards/performance-budgets.md` | skills |
| Assumptions | `docs/project/assumptions.md` | chat-only |
| Architecture decisions | `docs/project/decision-log.md` | ad-hoc notes |
| Builder input contract | `docs/templates/builder-task.md` | freeform prompts |
| Builder output contract | `docs/templates/builder-result.md` | — |
| Critic output | `docs/templates/critic-report.md` | — |
| Waivers | `docs/templates/waiver.md` + `qa/waivers.md` | — |
| Skill procedures | respective `.agents/skills/*/SKILL.md` | AGENTS.md |
| Agent roles | `.codex/agents/*.toml` | skills |

Audit status: PASS — no duplicated P0–P3 or browser matrix inside skills; skills reference standards.

Owner: QA Critic (role E)
Date: 2026-07-17

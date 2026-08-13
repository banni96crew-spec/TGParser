# Skill Inventory

Reference for [00-agent-preflight.mdc](../rules/00-agent-preflight.mdc) Pre-flight `Skills` line.
Match task keywords to a skill path, then `Read` that `SKILL.md` before work.

Owner contract for LLM assurance: [docs/engineering/LLM_ASSURANCE_MODEL.md](../../docs/engineering/LLM_ASSURANCE_MODEL.md).
Evidence claims outweigh self-reported `### Compliance` text (`AT-GOV-007`).

## Project skills (Telegram Lead Discovery governance)

| Skill | Path | Trigger keywords |
|-------|------|------------------|
| `agent-preflight` | `.cursor/skills/agent-preflight/SKILL.md` | preflight, compliance, sequential-thinking, first step |
| `verify` | `.cursor/skills/verify/SKILL.md` | verify change works, acceptance checks, green tests |
| `plan` | `.cursor/skills/plan/SKILL.md` | strategic plan, implementation plan, scope sequencing |
| `ralplan` | `.cursor/skills/ralplan/SKILL.md` | consensus planning, ralplan entrypoint |
| `merge-readiness` | `.cursor/skills/merge-readiness/SKILL.md` | merge gate, ready to merge, post-task checklist |

## Optional tooling (not product pipeline)

| Skill | Path | Trigger keywords |
|-------|------|------------------|
| `omc-reference` | `.cursor/skills/omc-reference/SKILL.md` | OMC agent catalog, available OMC tools |

## Quarantined (LeadGenerator website pipeline — do not use for this product)

These files remain on disk pending a separate deletion decision. Do **not** declare them in Pre-flight for Telegram Lead Discovery work.

| Skill | Path | Status |
|-------|------|--------|
| `gate-g1-capture` | `.cursor/skills/gate-g1-capture/SKILL.md` | quarantined |
| `gate-g2-audit-research` | `.cursor/skills/gate-g2-audit-research/SKILL.md` | quarantined |

## Usage in Pre-flight

```markdown
- Skills: .cursor/skills/agent-preflight/SKILL.md — complex governance task | none — trivial lookup
```

After listing, `Read` each declared skill before implementation when `Complex: yes`.

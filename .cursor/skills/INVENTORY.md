# Skill Inventory

Reference for [00-agent-preflight.mdc](../rules/00-agent-preflight.mdc) Pre-flight `Skills` line. Match task keywords to skill path, then `Read` the SKILL.md before work.

| Skill | Path | Trigger keywords |
|-------|------|------------------|
| `agent-preflight` | `.cursor/skills/agent-preflight/SKILL.md` | preflight, compliance, sequential-thinking, first step |
| `run-pipeline-stage` | `.cursor/skills/run-pipeline-stage/SKILL.md` | pipeline, orchestrator, state.json, gate-before-next-stage, --force |
| `resolve-lead` | `.cursor/skills/resolve-lead/SKILL.md` | lead.json, lead_id, slugify, --data, leads.xlsx |
| `capture-website` | `.cursor/skills/capture-website/SKILL.md` | Capture step, Playwright, desktop.png, mobile.png, capture/text.txt |
| `probe-site` | `.cursor/skills/probe-site/SKILL.md` | decideBranch, probeSite, has_website, branch routing |
| `validate-contract` | `.cursor/skills/validate-contract/SKILL.md` | ajv, schema validation, assertValid, schema_version |
| `gate-g1-capture` | `.cursor/skills/gate-g1-capture/SKILL.md` | G1, capture gate, screenshot size, text length |
| `gate-g2-audit-research` | `.cursor/skills/gate-g2-audit-research/SKILL.md` | G2, audit.json, research.json, findings evidence |
| `web-research-company` | `.cursor/skills/web-research-company/SKILL.md` | Firecrawl, Exa, no_website research, competitors |
| `brand-extraction` | `.cursor/skills/brand-extraction/SKILL.md` | brand_tokens, palette, font detection, logo path |
| `premium-website-designer` | `.cursor/skills/premium-website-designer/SKILL.md` | Design stage, design-system, premium UI, design/dist |
| `render-preview` | `.cursor/skills/render-preview/SKILL.md` | preview-desktop.png, preview-mobile.png, G4 previews |
| `deploy-cloudflare` | `.cursor/skills/deploy-cloudflare/SKILL.md` | Cloudflare Pages, deploy.json, demo_url, Publish |
| `smoke-test-url` | `.cursor/skills/smoke-test-url/SKILL.md` | G5 smoke, Lighthouse, console errors, demo URL |
| `generate-audit-pdf` | `.cursor/skills/generate-audit-pdf/SKILL.md` | audit.pdf, PDF export, offer package |
| `link-check` | `.cursor/skills/link-check/SKILL.md` | G6, offer links, demo_url 200, portfolio URL |
| `skill-creator` | `.cursor/skills/skill-creator/SKILL.md` | create skill, edit skill, skill evals |

## External skills (Cursor user)

| Skill | Path | Trigger keywords |
|-------|------|------------------|
| `create-hook` | `~/.cursor/skills-cursor/create-hook/SKILL.md` | hooks.json, preToolUse, sessionStart, Cursor hooks |

## Usage in Pre-flight

```markdown
- Skills: .cursor/skills/run-pipeline-stage/SKILL.md — user asked to run pipeline | none — trivial lookup
```

After listing, `Read` each declared skill before implementation when `Complex: yes`.

#!/usr/bin/env node
/**
 * validate-artifacts.mjs — G0–G4 markdown field presence checks
 * Usage: node scripts/validate-artifacts.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const required = [
  ["docs/project/assumptions.md", ["Assumption", "Owner"]],
  ["docs/project/decision-log.md", ["Decision"]],
  ["docs/standards/quality-gates.md", ["G0", "G5", "P0"]],
  ["docs/standards/browser-matrix.md", ["320", "1440"]],
  ["docs/standards/accessibility-standard.md", ["Axe", "44"]],
  ["docs/standards/performance-budgets.md", ["Lighthouse", "LCP"]],
  ["docs/templates/builder-task.md", ["Task ID", "In scope"]],
  ["docs/templates/builder-result.md", ["Изменённые файлы"]],
  ["docs/templates/critic-report.md", ["Блокирующие"]],
  ["docs/templates/waiver.md", ["Waiver ID"]],
  ["AGENTS.md", ["Sources of truth", "Verification"]],
];

let failed = 0;
for (const [rel, needles] of required) {
  const full = path.join(root, rel);
  if (!fs.existsSync(full)) {
    console.error(`FAIL missing: ${rel}`);
    failed++;
    continue;
  }
  const text = fs.readFileSync(full, "utf8");
  for (const n of needles) {
    if (!text.includes(n)) {
      console.error(`FAIL ${rel}: missing marker "${n}"`);
      failed++;
    }
  }
  if (failed === 0 || text) {
    // keep going
  }
}

const skills = [
  "landing-page-architecture",
  "design-system",
  "frontend-implementation",
  "visual-qa",
  "seo-performance",
];
for (const s of skills) {
  const skillMd = path.join(root, ".agents/skills", s, "SKILL.md");
  if (!fs.existsSync(skillMd)) {
    console.warn(`WARN skill not yet present: ${s}/SKILL.md`);
  } else {
    const t = fs.readFileSync(skillMd, "utf8");
    if (!t.includes("name:") || !t.includes("description:")) {
      console.error(`FAIL ${s}: SKILL.md missing frontmatter keys`);
      failed++;
    }
  }
}

if (failed > 0) {
  console.error(`validate-artifacts: ${failed} failure(s)`);
  process.exit(1);
}
console.log("validate-artifacts: PASS");

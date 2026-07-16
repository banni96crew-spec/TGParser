#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  canonicalJson,
  listFiles,
  readJson,
} from "./lib/quality-contract.mjs";
import { validateCapabilities } from "./validate-capabilities.mjs";

const EXPECTED_GATES = [
  "Capability fixtures и matrix",
  "Task profiles",
  "Conversation concurrency и idempotency",
  "Deterministic journal degradation",
  "Preventive bypass denial",
  "Valid profiles и latency",
  "Untrusted evidence claim",
  "Deterministic validators",
  "Git prerequisite",
  "CI tampering и stale SHA",
  "Hosted/Desktop verdict parity",
  "Transactional installer rollback",
  "Per-gate и out-of-band recovery",
];

const REQUIRED_FILES = [
  "docs/engineering/CHANGE_EVIDENCE.md",
  "docs/engineering/CI_OBSERVE_ONLY.md",
  "docs/engineering/GIT_HOSTING_PREREQUISITE.md",
  "docs/engineering/LLM_ASSURANCE_MODEL.md",
  "docs/engineering/LLM_QUALITY_RECOVERY.md",
  "docs/engineering/WINDOWS_SMOKE_CHECKLIST.md",
  "schemas/quality/capability-fixture.schema.json",
  "schemas/quality/evidence-claim.schema.json",
  "schemas/quality/journal-event.schema.json",
  "schemas/quality/task-contract.schema.json",
  ".cursor/hooks/policy-manifest.json",
  "tools/quality/ci-recompute.mjs",
  "tools/quality/lib/conversation-journal.mjs",
  "tools/quality/lib/evidence-checkpoint.mjs",
  "tools/quality/lib/policy-engine.mjs",
  "tools/quality/lib/quality-contract.mjs",
  "tools/quality/recover-hooks.ps1",
  "tools/quality/run-quality-suite.mjs",
  "tools/quality/validate-capabilities.mjs",
  "tools/quality/validate-governance.mjs",
  "tools/quality/validate-journal.mjs",
  "tools/quality/validate-prd.py",
  "tools/quality/verify-local-claim.mjs",
];

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function checkLinks(root, files, errors) {
  const expression = /\[[^\]]+]\(([^)]+)\)/g;
  for (const filePath of files) {
    const text = await fs.readFile(filePath, "utf8");
    for (const match of text.matchAll(expression)) {
      const target = match[1].split("#")[0];
      if (!target || /^(?:https?:|mailto:)/i.test(target)) continue;
      let decoded;
      try {
        decoded = decodeURIComponent(target);
      } catch {
        errors.push(`${path.relative(root, filePath)}: invalid link encoding: ${target}`);
        continue;
      }
      const resolved = path.resolve(path.dirname(filePath), decoded);
      if (!(await pathExists(resolved))) {
        errors.push(`${path.relative(root, filePath)}: missing link target: ${target}`);
      }
    }
  }
}

export async function validateGovernance(root = process.cwd()) {
  const errors = [];
  for (const relative of REQUIRED_FILES) {
    if (!(await pathExists(path.join(root, relative)))) {
      errors.push(`missing required file: ${relative}`);
    }
  }

  const ownerPath = path.join(
    root,
    "docs",
    "engineering",
    "LLM_ASSURANCE_MODEL.md",
  );
  const owner = await fs.readFile(ownerPath, "utf8");
  const requirements = [
    ...owner.matchAll(/^### GOV-(\d{3}) — (.+)$/gm),
  ].map((match) => ({ number: match[1], title: match[2] }));
  const acceptance = [...owner.matchAll(/^\*\*AT-GOV-(\d{3}):/gm)].map(
    (match) => match[1],
  );
  const expectedNumbers = EXPECTED_GATES.map((_, index) =>
    String(index + 1).padStart(3, "0"),
  );
  if (
    requirements.map((item) => item.number).join(",") !==
    expectedNumbers.join(",")
  ) {
    errors.push("GOV sequence must be GOV-001..GOV-013");
  }
  if (acceptance.join(",") !== expectedNumbers.join(",")) {
    errors.push("AT-GOV sequence must be AT-GOV-001..AT-GOV-013");
  }
  requirements.forEach((requirement, index) => {
    if (requirement.title !== EXPECTED_GATES[index]) {
      errors.push(`GOV-${requirement.number} title mismatch`);
    }
  });

  const schemaRoot = path.join(root, "schemas", "quality");
  const schemaPaths = await listFiles(schemaRoot, (file) =>
    file.endsWith(".schema.json"),
  );
  for (const schemaPath of schemaPaths) {
    const schema = await readJson(schemaPath);
    const relative = path.relative(root, schemaPath);
    if (schema.$schema !== "https://json-schema.org/draft/2020-12/schema") {
      errors.push(`${relative}: JSON Schema draft mismatch`);
    }
    if (schema.additionalProperties !== false) {
      errors.push(`${relative}: top-level additionalProperties must be false`);
    }
    if (!schema.properties?.schema_version?.const) {
      errors.push(`${relative}: explicit schema_version const missing`);
    }
  }

  const docs = [
    path.join(root, "AGENTS.md"),
    ...(await listFiles(path.join(root, "docs", "engineering"), (file) =>
      file.endsWith(".md"),
    )),
  ];
  await checkLinks(root, docs, errors);

  const productFiles = await listFiles(path.join(root, "docs", "prd"), (file) =>
    file.endsWith(".md"),
  );
  for (const filePath of productFiles) {
    if (/\b(?:AT-)?GOV-\d{3}\b/.test(await fs.readFile(filePath, "utf8"))) {
      errors.push(`governance ID leaked into product PRD: ${path.relative(root, filePath)}`);
    }
  }

  const capabilities = await validateCapabilities(root);
  errors.push(...capabilities.errors.map((error) => `capabilities: ${error}`));
  return {
    schema_version: "1.0.0",
    validator: "validate-governance",
    status: errors.length === 0 ? "pass" : "fail",
    errors: errors.sort(),
    counts: {
      acceptance_tests: acceptance.length,
      capability_events: capabilities.matrix.length,
      governance_requirements: requirements.length,
      schemas: schemaPaths.length,
    },
  };
}

async function main() {
  const root = process.argv[2] ? path.resolve(process.argv[2]) : process.cwd();
  const result = await validateGovernance(root);
  process.stdout.write(canonicalJson(result));
  if (result.status !== "pass") process.exitCode = 1;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  await main();
}

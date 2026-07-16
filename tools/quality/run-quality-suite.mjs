#!/usr/bin/env node
/**
 * Windows-friendly orchestration for local quality suite (no package.json deps).
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { canonicalJson } from "./lib/quality-contract.mjs";

const root = process.cwd();

function run(label, command, args) {
  const started = Date.now();
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
    shell: false,
  });
  return {
    label,
    command: [command, ...args].join(" "),
    status: result.status === 0 ? "pass" : "fail",
    exit_code: result.status ?? 1,
    duration_ms: Date.now() - started,
    stderr_tail: (result.stderr ?? "").slice(-500),
  };
}

const steps = [
  run("node-tests", process.execPath, [
    "--test",
    "tests/quality/hooks.test.mjs",
    "tests/quality/policy-engine.test.mjs",
    "tests/quality/conversation-journal.test.mjs",
    "tests/quality/validators.test.mjs",
    "tests/quality/evidence-gates.test.mjs",
  ]),
  run("validate-capabilities", process.execPath, [
    "tools/quality/validate-capabilities.mjs",
  ]),
  run("validate-governance", process.execPath, [
    "tools/quality/validate-governance.mjs",
  ]),
  run("validate-prd", "python", ["tools/quality/validate-prd.py"]),
  run("ci-recompute", process.execPath, ["tools/quality/ci-recompute.mjs"]),
];

const failed = steps.filter((step) => step.status !== "pass");
const report = {
  schema_version: "1.0.0",
  suite: "run-quality-suite",
  status: failed.length === 0 ? "pass" : "fail",
  steps,
};
process.stdout.write(canonicalJson(report));
process.exitCode = failed.length === 0 ? 0 : 1;

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  // already executed above
}

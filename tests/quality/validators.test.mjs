import assert from "node:assert/strict";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  verifyUntrustedEvidenceClaim,
} from "../../tools/quality/lib/quality-contract.mjs";
import {
  validateJournalText,
} from "../../tools/quality/validate-journal.mjs";

const root = path.resolve(".");

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      windowsHide: true,
      ...options,
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.setEncoding("utf8");
    child.stderr?.setEncoding("utf8");
    child.stdout?.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

test("Node validators are deterministic and green on repository fixtures", async () => {
  const commands = [
    ["tools/quality/validate-capabilities.mjs"],
    ["tools/quality/validate-governance.mjs"],
    [
      "tools/quality/validate-journal.mjs",
      "tests/fixtures/quality/journals/valid.jsonl",
    ],
  ];
  for (const args of commands) {
    const first = await run(process.execPath, args);
    const second = await run(process.execPath, args);
    assert.equal(first.code, 0, `${args[0]}: ${first.stderr}${first.stdout}`);
    assert.equal(second.code, 0);
    assert.equal(first.stdout, second.stdout);
    assert.equal(JSON.parse(first.stdout).status, "pass");
  }
});

test("Python PRD validator is deterministic and green", async () => {
  const first = await run("python", ["tools/quality/validate-prd.py"]);
  const second = await run("python", ["tools/quality/validate-prd.py"]);
  assert.equal(first.code, 0, first.stderr + first.stdout);
  assert.equal(second.code, 0);
  assert.equal(first.stdout, second.stdout);
  const result = JSON.parse(first.stdout);
  assert.equal(result.status, "pass");
  assert.equal(result.counts.requirements, 195);
  assert.equal(result.counts.acceptance_tests, 195);
});

test("malformed and truncated journal validation is deterministic", async () => {
  const malformed = '{"schema_version":"1.1.0"\n';
  const truncated = '{"schema_version":"1.1.0"}';
  assert.deepEqual(
    validateJournalText(malformed, "fixture"),
    validateJournalText(malformed, "fixture"),
  );
  assert.ok(validateJournalText(malformed, "fixture").errors.length > 0);
  assert.ok(
    validateJournalText(truncated, "fixture").errors.includes(
      "fixture: truncated tail",
    ),
  );
  const cli = await run(process.execPath, [
    "tools/quality/validate-journal.mjs",
    "tests/fixtures/quality/journals/malformed.jsonl",
  ]);
  assert.equal(cli.code, 1);
  assert.equal(JSON.parse(cli.stdout).status, "fail");
});

test("tampered hashes and stale SHA cannot become trusted PASS", () => {
  const claim = {
    trust: "untrusted_local_claim",
    evidence_scope: "local",
    base_sha: "a".repeat(40),
    head_sha: "b".repeat(40),
    observed_files: [{ path: "tools/quality/x.mjs", sha256: "c".repeat(64) }],
  };
  const verified = verifyUntrustedEvidenceClaim(claim, {
    base_sha: "d".repeat(40),
    head_sha: "e".repeat(40),
    observed_hashes: { "tools/quality/x.mjs": "f".repeat(64) },
  });
  assert.equal(verified.trusted, false);
  assert.equal(verified.verdict, "fail");
  assert.deepEqual(verified.errors, [
    "observed hash mismatch: tools/quality/x.mjs",
    "stale base_sha",
    "stale head_sha",
  ]);
});

test("operator recovery verifies checksum and restores atomically in temp project", async (t) => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "quality-recovery-"));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  const cursor = path.join(temp, ".cursor");
  await fs.mkdir(cursor);
  const target = path.join(cursor, "hooks.json");
  const backup = path.join(temp, "known-good.json");
  const original = '{"version":1,"hooks":{"stop":[]}}\n';
  const knownGood = '{"version":1,"hooks":{"sessionStart":[]}}\n';
  await fs.writeFile(target, original, "utf8");
  await fs.writeFile(backup, knownGood, "utf8");
  const checksum = crypto.createHash("sha256").update(knownGood).digest("hex");
  const result = await run("powershell", [
    "-NoProfile",
    "-File",
    "tools/quality/recover-hooks.ps1",
    "-BackupPath",
    backup,
    "-ExpectedSha256",
    checksum,
    "-ConfirmRestore",
    "-ProjectRoot",
    temp,
  ]);
  assert.equal(result.code, 0, result.stderr + result.stdout);
  assert.equal(await fs.readFile(target, "utf8"), knownGood);

  await fs.writeFile(target, original, "utf8");
  const rejected = await run("powershell", [
    "-NoProfile",
    "-File",
    "tools/quality/recover-hooks.ps1",
    "-BackupPath",
    backup,
    "-ExpectedSha256",
    "0".repeat(64),
    "-ConfirmRestore",
    "-ProjectRoot",
    temp,
  ]);
  assert.notEqual(rejected.code, 0);
  assert.equal(await fs.readFile(target, "utf8"), original);
});

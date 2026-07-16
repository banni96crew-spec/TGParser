import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  buildEvidenceClaim,
  clearCheckpointDebounce,
  recordEvidenceCheckpoint,
  verifyLocalClaimFile,
  writeEvidenceClaim,
} from "../../tools/quality/lib/evidence-checkpoint.mjs";
import { sha256 } from "../../tools/quality/lib/quality-contract.mjs";

const root = path.resolve(".");

function runHook(script, payload, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script], {
      cwd: root,
      env: { ...process.env, ...env },
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.stdin.end(JSON.stringify(payload));
  });
}

test("tampered evidence claim fails independent recomputation", async (t) => {
  clearCheckpointDebounce();
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "quality-claim-"));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  const relative = "docs/engineering/README.md";
  const absolute = path.join(temp, relative);
  await fs.mkdir(path.dirname(absolute), { recursive: true });
  await fs.writeFile(absolute, "trusted-bytes", "utf8");
  const claimsDirectory = path.join(temp, ".cursor", "quality-claims");
  const claim = buildEvidenceClaim({
    conversationId: "conversation-claim",
    taskId: "task-claim",
    requirementIds: ["GOV-007"],
    claim: "local hash evidence",
    observedFiles: [
      {
        path: relative,
        sha256: sha256("trusted-bytes"),
      },
    ],
    requestedChecks: ["hash-recompute"],
    unresolvedFailures: [],
    evidenceRefs: ["docs/engineering/README.md"],
    status: "pass",
  });
  const written = await writeEvidenceClaim(claim, {
    root: temp,
    claimsDirectory,
  });
  const ok = await verifyLocalClaimFile(written.absolute, { root: temp });
  assert.equal(ok.trusted, false);
  assert.equal(ok.verdict, "untrusted");
  assert.deepEqual(ok.errors, []);

  await fs.writeFile(absolute, "tampered-bytes", "utf8");
  const failed = await verifyLocalClaimFile(written.absolute, { root: temp });
  assert.equal(failed.trusted, false);
  assert.equal(failed.verdict, "fail");
  assert.ok(
    failed.errors.some((item) => item.includes("observed hash mismatch")),
  );

  const cli = await new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      ["tools/quality/verify-local-claim.mjs", written.absolute],
      {
        cwd: root,
        env: { ...process.env, CURSOR_PROJECT_DIR: temp },
        windowsHide: true,
      },
    );
    let stdout = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout }));
  });
  assert.equal(cli.code, 1);
  assert.equal(JSON.parse(cli.stdout).verdict, "fail");
  assert.equal(JSON.parse(cli.stdout).trusted, false);
});

test("checkpoint helper writes schema-compliant untrusted claim", async (t) => {
  clearCheckpointDebounce();
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "quality-checkpoint-"));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  await fs.mkdir(path.join(temp, "tools", "quality"), { recursive: true });
  const sample = path.join(temp, "tools", "quality", "sample.txt");
  await fs.writeFile(sample, "checkpoint", "utf8");
  const claimsDirectory = path.join(temp, ".cursor", "quality-claims");
  const result = await recordEvidenceCheckpoint(
    {
      conversationId: "conversation-checkpoint",
      paths: ["tools/quality/sample.txt"],
      root: temp,
      claimsDirectory,
      explicit: true,
      runValidators: false,
    },
  );
  assert.equal(result.deferred, false);
  assert.equal(result.claim.trust, "untrusted_local_claim");
  assert.equal(result.claim.evidence_scope, "local");
  assert.equal(result.claim.schema_version, "1.1.0");
  assert.equal(result.claim.observed_files[0].path, "tools/quality/sample.txt");
  assert.equal(
    result.claim.observed_files[0].sha256,
    sha256("checkpoint"),
  );
});

test("stop audit remains allow with bounded advisory followup", async (t) => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "quality-stop-"));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  const statePath = path.join(temp, "session-compliance.json");
  await fs.writeFile(
    statePath,
    JSON.stringify({
      sequential_thinking_done: true,
      sequential_thinking_calls: 1,
      session_id: "session-stop",
    }),
    "utf8",
  );
  const result = await runHook(
    path.join(root, ".cursor", "hooks", "audit-compliance.mjs"),
    { conversation_id: "conversation-stop-advisory" },
    {
      COMPLIANCE_STATE_PATH: statePath,
      CURSOR_PROJECT_DIR: temp,
      QUALITY_CLAIMS_DIR: path.join(temp, "missing-claims"),
      QUALITY_JOURNAL_DIR: path.join(temp, "missing-journals"),
    },
  );
  assert.equal(result.code, 0);
  const output = JSON.parse(result.stdout);
  assert.equal(output.permission, "allow");
  assert.match(output.followup_message ?? "", /evidence claim/i);
});

test("stop audit allow without followup when claim exists and ST done", async (t) => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "quality-stop-ok-"));
  t.after(() => fs.rm(temp, { recursive: true, force: true }));
  const statePath = path.join(temp, "session-compliance.json");
  await fs.writeFile(
    statePath,
    JSON.stringify({
      sequential_thinking_done: true,
      sequential_thinking_calls: 1,
      session_id: "session-stop-ok",
    }),
    "utf8",
  );
  const claimsDirectory = path.join(temp, ".cursor", "quality-claims");
  await fs.mkdir(claimsDirectory, { recursive: true });
  await fs.writeFile(
    path.join(claimsDirectory, "claim-present.json"),
    JSON.stringify({ ok: true }),
    "utf8",
  );
  const result = await runHook(
    path.join(root, ".cursor", "hooks", "audit-compliance.mjs"),
    { conversation_id: "conversation-stop-ok" },
    {
      COMPLIANCE_STATE_PATH: statePath,
      CURSOR_PROJECT_DIR: temp,
      QUALITY_CLAIMS_DIR: claimsDirectory,
      QUALITY_JOURNAL_DIR: path.join(temp, "journals"),
    },
  );
  assert.equal(result.code, 0);
  assert.deepEqual(JSON.parse(result.stdout), { permission: "allow" });
});

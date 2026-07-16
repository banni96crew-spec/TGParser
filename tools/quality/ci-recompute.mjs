#!/usr/bin/env node
/**
 * Observe-only CI recomputation helper (AT-GOV-009 / AT-GOV-010 scaffolding).
 * Does not create .github/workflows. Without Git prerequisites → status not_run.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { canonicalJson, sha256 } from "./lib/quality-contract.mjs";
import { verifyLocalClaimFile } from "./lib/evidence-checkpoint.mjs";

function git(args, cwd) {
  const result = spawnSync("git", args, {
    cwd,
    encoding: "utf8",
    windowsHide: true,
  });
  return {
    ok: result.status === 0,
    stdout: (result.stdout ?? "").trim(),
    stderr: (result.stderr ?? "").trim(),
    status: result.status ?? 1,
  };
}

function hasGitRepo(cwd) {
  const probe = git(["rev-parse", "--is-inside-work-tree"], cwd);
  return probe.ok && probe.stdout === "true";
}

export function recomputeCiObserveOnly({
  root = process.cwd(),
  claimPath = null,
} = {}) {
  const cwd = root;
  if (!hasGitRepo(cwd)) {
    return {
      schema_version: "1.0.0",
      tool: "ci-recompute",
      mode: "observe_only",
      status: "not_run",
      at_gov_009: "not_run",
      at_gov_010: "not_run",
      reason: "git_prerequisite_missing",
      authoritative_ci: "blocked",
      required_merge_protection: "blocked",
      errors: [],
    };
  }

  const head = git(["rev-parse", "HEAD"], cwd);
  const remote = git(["remote"], cwd);
  const errors = [];
  if (!head.ok) errors.push("unable_to_read_head_sha");
  if (!remote.ok || remote.stdout === "") {
    errors.push("git_remote_missing");
  }

  const changed = git(["diff", "--name-only", "HEAD"], cwd);
  const files = changed.ok
    ? changed.stdout.split(/\r?\n/).filter(Boolean).sort()
    : [];
  const hashes = {};
  for (const relative of files) {
    try {
      hashes[relative.replaceAll("\\", "/")] = sha256(
        fs.readFileSync(path.join(cwd, relative)),
      );
    } catch {
      errors.push(`unreadable_changed_file:${relative}`);
    }
  }

  let claimVerification = null;
  if (claimPath) {
    // sync wrapper via spawn would be heavier; callers use async path in tests
    claimVerification = { deferred: true, note: "use verify-local-claim.mjs" };
  }

  const status = errors.length > 0 ? "fail" : "pass";
  return {
    schema_version: "1.0.0",
    tool: "ci-recompute",
    mode: "observe_only",
    status,
    at_gov_009: remote.ok && remote.stdout !== "" ? "local_only" : "not_run",
    at_gov_010: "not_run",
    reason:
      remote.ok && remote.stdout !== ""
        ? "git_present_but_authoritative_ci_blocked_pending_hosting"
        : "git_remote_or_hosting_incomplete",
    authoritative_ci: "blocked",
    required_merge_protection: "blocked",
    head_sha: head.ok ? head.stdout : null,
    remotes: remote.ok ? remote.stdout.split(/\r?\n/).filter(Boolean) : [],
    changed_files: files.map((file) => file.replaceAll("\\", "/")),
    recomputed_hashes: hashes,
    claim_verification: claimVerification,
    errors: errors.sort(),
  };
}

async function main() {
  const root = process.argv[2] ? path.resolve(process.argv[2]) : process.cwd();
  const claimArg = process.argv.find((arg) => arg.startsWith("--claim="));
  const claimPath = claimArg ? claimArg.slice("--claim=".length) : null;
  const result = recomputeCiObserveOnly({ root, claimPath });
  if (claimPath && result.status !== "not_run") {
    const verified = await verifyLocalClaimFile(claimPath, { root });
    result.claim_verification = {
      trusted: false,
      verdict: verified.verdict,
      errors: verified.errors,
    };
    if (verified.verdict === "fail") {
      result.status = "fail";
      result.errors = [...result.errors, ...verified.errors].sort();
    }
  }
  process.stdout.write(canonicalJson(result));
  if (result.status === "fail") process.exitCode = 1;
  if (result.status === "not_run") process.exitCode = 0;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  await main();
}

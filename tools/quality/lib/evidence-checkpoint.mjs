import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  CONTRACT_VERSION,
  canonicalize,
  canonicalJson,
  normalizeConversationId,
  normalizeRepoPath,
  sha256,
  verifyUntrustedEvidenceClaim,
} from "./quality-contract.mjs";

const DEFAULT_DEBOUNCE_MS = 1_500;
const SECRET_PATTERNS = [
  /(?:api[_-]?key|secret|password|token)\s*[:=]\s*['"][^'"]{8,}/i,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /(?:sk|pk)-[a-zA-Z0-9]{20,}/,
];

const debounceState = new Map();

function projectRoot(root) {
  return root ?? process.env.CURSOR_PROJECT_DIR ?? process.cwd();
}

function claimsDir(root) {
  return (
    process.env.QUALITY_CLAIMS_DIR ??
    path.join(projectRoot(root), ".cursor", "quality-claims")
  );
}

export function validateEvidenceClaimShape(claim) {
  const errors = [];
  if (!claim || typeof claim !== "object" || Array.isArray(claim)) {
    return ["claim must be an object"];
  }
  if (claim.schema_version !== CONTRACT_VERSION) {
    errors.push(`schema_version must equal ${CONTRACT_VERSION}`);
  }
  for (const field of [
    "claim_id",
    "conversation_id",
    "task_id",
    "claim",
    "recorded_at",
  ]) {
    if (typeof claim[field] !== "string" || claim[field].trim() === "") {
      errors.push(`${field} must be a non-empty string`);
    }
  }
  if (claim.trust !== "untrusted_local_claim") {
    errors.push("trust must equal untrusted_local_claim");
  }
  if (claim.evidence_scope !== "local") {
    errors.push("evidence_scope must equal local");
  }
  if (!["pass", "fail", "not_run", "unsupported"].includes(claim.status)) {
    errors.push("status is unsupported");
  }
  for (const field of [
    "requirement_ids",
    "evidence_refs",
    "observed_files",
    "requested_checks",
    "unresolved_failures",
  ]) {
    if (!Array.isArray(claim[field])) errors.push(`${field} must be an array`);
  }
  if (claim.status === "pass" && (claim.evidence_refs?.length ?? 0) < 1) {
    errors.push("pass claims require evidence_refs");
  }
  for (const file of claim.observed_files ?? []) {
    if (
      !file ||
      typeof file.path !== "string" ||
      typeof file.sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(file.sha256)
    ) {
      errors.push("observed_files entries require path and sha256");
    }
  }
  return errors.sort();
}

export async function hashRepoFiles(root, relativePaths) {
  const observed = [];
  const hashes = {};
  for (const raw of relativePaths) {
    const relative = normalizeRepoPath(raw);
    const absolute = path.join(projectRoot(root), relative);
    const digest = sha256(await fs.readFile(absolute));
    observed.push({ path: relative, sha256: digest });
    hashes[relative] = digest;
  }
  observed.sort((left, right) => left.path.localeCompare(right.path));
  return { observed_files: observed, observed_hashes: hashes };
}

export function scanGovernanceSecrets(text, relativePath) {
  const findings = [];
  for (const pattern of SECRET_PATTERNS) {
    if (pattern.test(text)) {
      findings.push(`secret_pattern:${relativePath}`);
    }
  }
  return findings;
}

export async function scanPathsForSecrets(root, relativePaths) {
  const findings = [];
  for (const raw of relativePaths) {
    const relative = normalizeRepoPath(raw);
    if (
      !relative.startsWith("docs/engineering/") &&
      !relative.startsWith("schemas/quality/") &&
      !relative.startsWith("tools/quality/") &&
      !relative.startsWith(".cursor/")
    ) {
      continue;
    }
    try {
      const text = await fs.readFile(
        path.join(projectRoot(root), relative),
        "utf8",
      );
      findings.push(...scanGovernanceSecrets(text, relative));
    } catch {
      findings.push(`unreadable:${relative}`);
    }
  }
  return [...new Set(findings)].sort();
}

function runProcess(command, args, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd,
      windowsHide: true,
      env: process.env,
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
    child.on("error", (error) => {
      resolve({ code: 1, stdout, stderr: String(error) });
    });
    child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
  });
}

export async function runLocalGovernanceChecks(root = process.cwd()) {
  const cwd = projectRoot(root);
  const checks = [
    {
      id: "validate-governance",
      command: process.execPath,
      args: ["tools/quality/validate-governance.mjs"],
    },
    {
      id: "validate-prd",
      command: "python",
      args: ["tools/quality/validate-prd.py"],
    },
  ];
  const results = [];
  for (const check of checks) {
    const outcome = await runProcess(check.command, check.args, cwd);
    results.push({
      id: check.id,
      status: outcome.code === 0 ? "pass" : "fail",
      exit_code: outcome.code,
    });
  }
  return results;
}

export function buildEvidenceClaim({
  conversationId,
  taskId,
  requirementIds,
  claim,
  observedFiles,
  requestedChecks,
  unresolvedFailures = [],
  evidenceRefs = [],
  status,
  claimId,
  recordedAt = new Date().toISOString(),
  baseSha,
  headSha,
  supersedesClaimId,
}) {
  const payload = {
    schema_version: CONTRACT_VERSION,
    claim_id: claimId ?? `claim-${sha256(`${conversationId}:${taskId}:${recordedAt}`).slice(0, 16)}`,
    conversation_id: normalizeConversationId(conversationId),
    task_id: taskId,
    requirement_ids: [...requirementIds].sort(),
    claim,
    trust: "untrusted_local_claim",
    evidence_scope: "local",
    status,
    evidence_refs: [...evidenceRefs].sort(),
    observed_files: canonicalize(observedFiles),
    requested_checks: [...requestedChecks].sort(),
    unresolved_failures: [...unresolvedFailures].sort(),
    recorded_at: recordedAt,
  };
  if (baseSha) payload.base_sha = baseSha;
  if (headSha) payload.head_sha = headSha;
  if (supersedesClaimId) payload.supersedes_claim_id = supersedesClaimId;
  return payload;
}

export async function writeEvidenceClaim(claim, { root, claimsDirectory } = {}) {
  const shapeErrors = validateEvidenceClaimShape(claim);
  if (shapeErrors.length > 0) {
    throw new TypeError(`invalid evidence claim: ${shapeErrors.join("; ")}`);
  }
  const directory = claimsDirectory ?? claimsDir(root);
  await fs.mkdir(directory, { recursive: true });
  const fileName = `${claim.claim_id}.json`;
  const absolute = path.join(directory, fileName);
  await fs.writeFile(absolute, canonicalJson(claim), "utf8");
  return {
    path: path.relative(projectRoot(root), absolute).replaceAll("\\", "/"),
    absolute,
    claim,
  };
}

export async function recordEvidenceCheckpoint(
  {
    conversationId,
    taskId = "local-checkpoint",
    requirementIds = ["GOV-007", "GOV-008"],
    paths = [],
    claimText = "local governance checkpoint",
    root,
    claimsDirectory,
    runValidators = true,
    explicit = false,
    debounceMs = DEFAULT_DEBOUNCE_MS,
  } = {},
  helpers = {},
) {
  const cwd = projectRoot(root);
  const key = normalizeConversationId(conversationId ?? "anonymous");
  if (!explicit) {
    const previous = debounceState.get(key) ?? 0;
    const now = Date.now();
    if (now - previous < debounceMs) {
      return { deferred: true, reason: "debounced" };
    }
    debounceState.set(key, now);
  }

  const uniquePaths = [...new Set(paths.map(normalizeRepoPath))].sort();
  const hashed = await (helpers.hashRepoFiles ?? hashRepoFiles)(cwd, uniquePaths);
  const secretFindings = await (helpers.scanPathsForSecrets ?? scanPathsForSecrets)(
    cwd,
    uniquePaths,
  );
  const checkResults = runValidators
    ? await (helpers.runLocalGovernanceChecks ?? runLocalGovernanceChecks)(cwd)
    : [];
  const failedChecks = checkResults
    .filter((item) => item.status !== "pass")
    .map((item) => item.id);
  const unresolved = [...secretFindings, ...failedChecks].sort();
  const status =
    unresolved.length > 0
      ? "fail"
      : checkResults.length === 0 && uniquePaths.length === 0
        ? "not_run"
        : "pass";
  const claim = buildEvidenceClaim({
    conversationId: key,
    taskId,
    requirementIds,
    claim: claimText,
    observedFiles: hashed.observed_files,
    requestedChecks: [
      ...checkResults.map((item) => item.id),
      "secret-scope-scan",
    ],
    unresolvedFailures: unresolved,
    evidenceRefs:
      status === "pass"
        ? [
            "tools/quality/validate-governance.mjs",
            "tools/quality/validate-prd.py",
          ]
        : [],
    status,
  });
  const written = await writeEvidenceClaim(claim, {
    root: cwd,
    claimsDirectory,
  });
  return {
    deferred: false,
    status,
    claim_path: written.path,
    claim: written.claim,
    observed_hashes: hashed.observed_hashes,
  };
}

export async function verifyLocalClaimFile(claimPath, { root } = {}) {
  const cwd = projectRoot(root);
  const absolute = path.isAbsolute(claimPath)
    ? claimPath
    : path.join(cwd, claimPath);
  const claim = JSON.parse(await fs.readFile(absolute, "utf8"));
  const shapeErrors = validateEvidenceClaimShape(claim);
  if (shapeErrors.length > 0) {
    return {
      trusted: false,
      verdict: "fail",
      errors: shapeErrors,
      claim,
    };
  }
  const observed_hashes = {};
  for (const file of claim.observed_files) {
    const absoluteFile = path.join(cwd, file.path);
    try {
      observed_hashes[file.path] = sha256(await fs.readFile(absoluteFile));
    } catch {
      observed_hashes[file.path] = null;
    }
  }
  const recomputed = verifyUntrustedEvidenceClaim(claim, {
    observed_hashes,
    base_sha: claim.base_sha,
    head_sha: claim.head_sha,
  });
  const missing = Object.entries(observed_hashes)
    .filter(([, digest]) => digest === null)
    .map(([filePath]) => `missing_file:${filePath}`);
  const mismatch = Object.entries(observed_hashes)
    .filter(
      ([filePath, digest]) =>
        digest !== null &&
        claim.observed_files.some(
          (file) => file.path === filePath && file.sha256 !== digest,
        ),
    )
    .map(([filePath]) => `recomputed_hash_mismatch:${filePath}`);
  const errors = [...recomputed.errors, ...missing, ...mismatch].sort();
  return {
    trusted: false,
    verdict: errors.length === 0 ? "untrusted" : "fail",
    errors,
    claim,
    observed_hashes,
  };
}

export function clearCheckpointDebounce() {
  debounceState.clear();
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  const mode = process.argv[2] ?? "checkpoint";
  if (mode === "checkpoint") {
    const conversationId = process.argv[3] ?? "manual-checkpoint";
    const paths = process.argv.slice(4);
    const result = await recordEvidenceCheckpoint({
      conversationId,
      paths,
      explicit: true,
    });
    process.stdout.write(canonicalJson(result));
    if (result.status === "fail") process.exitCode = 1;
  }
}

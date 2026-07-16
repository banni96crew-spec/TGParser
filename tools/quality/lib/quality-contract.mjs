import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

export const CONTRACT_VERSION = "1.1.0";
export const PROFILES = Object.freeze([
  "read_only",
  "documentation_mutation",
  "product_mutation",
]);
export const JOURNAL_EVENT_TYPES = Object.freeze([
  "policy",
  "tool",
  "edit",
  "check",
  "recovery",
]);

export function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function canonicalize(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

export function canonicalJson(value) {
  return `${JSON.stringify(canonicalize(value), null, 2)}\n`;
}

export function normalizeConversationId(value) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError("conversation_id must be a non-empty string");
  }
  return value.trim().normalize("NFC");
}

export function normalizeRepoPath(value) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError("path must be a non-empty string");
  }
  let decoded = value.trim();
  try {
    decoded = decodeURIComponent(decoded);
  } catch {
    throw new TypeError("path contains invalid percent encoding");
  }
  const normalized = path.posix
    .normalize(decoded.replaceAll("\\", "/"))
    .replace(/^\.\/+/, "")
    .normalize("NFC");
  if (normalized === ".." || normalized.startsWith("../")) {
    throw new TypeError("path escapes repository root");
  }
  return normalized;
}

function stringArray(value, field, { minItems = 0 } = {}) {
  if (!Array.isArray(value) || value.length < minItems) {
    return [`${field} must be an array with at least ${minItems} item(s)`];
  }
  if (value.some((item) => typeof item !== "string" || item.length === 0)) {
    return [`${field} must contain non-empty strings`];
  }
  if (new Set(value).size !== value.length) {
    return [`${field} must contain unique values`];
  }
  return [];
}

export function validateTaskContract(contract) {
  const errors = [];
  if (!contract || typeof contract !== "object" || Array.isArray(contract)) {
    return ["task contract must be an object"];
  }
  const allowed = new Set([
    "schema_version",
    "conversation_id",
    "task_id",
    "profile",
    "allowed_paths",
    "denied_paths",
    "owner_documents",
    "requirement_ids",
    "required_checks",
    "approval",
    "allowed_mcp_tools",
  ]);
  for (const key of Object.keys(contract)) {
    if (!allowed.has(key)) errors.push(`unknown task contract property: ${key}`);
  }
  if (contract.schema_version !== CONTRACT_VERSION) {
    errors.push(`schema_version must equal ${CONTRACT_VERSION}`);
  }
  for (const field of ["conversation_id", "task_id"]) {
    if (typeof contract[field] !== "string" || contract[field].trim() === "") {
      errors.push(`${field} must be a non-empty string`);
    }
  }
  if (!PROFILES.includes(contract.profile)) errors.push("profile is unsupported");
  errors.push(...stringArray(contract.allowed_paths, "allowed_paths"));
  errors.push(...stringArray(contract.denied_paths, "denied_paths", { minItems: 1 }));
  errors.push(
    ...stringArray(contract.owner_documents, "owner_documents", { minItems: 1 }),
  );
  errors.push(...stringArray(contract.requirement_ids, "requirement_ids"));
  errors.push(...stringArray(contract.required_checks, "required_checks"));
  if (contract.allowed_mcp_tools !== undefined) {
    errors.push(...stringArray(contract.allowed_mcp_tools, "allowed_mcp_tools"));
  }
  const approval = contract.approval;
  if (!approval || typeof approval !== "object" || Array.isArray(approval)) {
    errors.push("approval must be an object");
  } else {
    const keys = Object.keys(approval);
    if (keys.some((key) => !["status", "approved_by"].includes(key))) {
      errors.push("approval contains unknown properties");
    }
    if (!["approved", "not_required", "pending", "denied"].includes(approval.status)) {
      errors.push("approval.status is unsupported");
    }
    if (
      approval.approved_by !== null &&
      (typeof approval.approved_by !== "string" || approval.approved_by === "")
    ) {
      errors.push("approval.approved_by must be a non-empty string or null");
    }
    if (approval.status === "approved" && !approval.approved_by) {
      errors.push("approved contract requires approval.approved_by");
    }
  }
  if (
    contract.profile === "read_only" &&
    contract.approval?.status !== "not_required"
  ) {
    errors.push("read_only profile requires approval.status not_required");
  }
  if (
    contract.profile !== "read_only" &&
    contract.approval?.status !== "approved"
  ) {
    errors.push("mutation profiles require explicit approval");
  }
  return errors.sort();
}

export function verifyUntrustedEvidenceClaim(claim, observation) {
  const errors = [];
  if (claim?.trust !== "untrusted_local_claim" || claim?.evidence_scope !== "local") {
    errors.push("claim trust boundary is invalid");
  }
  const observedHashes = observation?.observed_hashes ?? {};
  for (const file of claim?.observed_files ?? []) {
    if (observedHashes[file.path] !== file.sha256) {
      errors.push(`observed hash mismatch: ${file.path}`);
    }
  }
  if (claim?.base_sha && claim.base_sha !== observation?.base_sha) {
    errors.push("stale base_sha");
  }
  if (claim?.head_sha && claim.head_sha !== observation?.head_sha) {
    errors.push("stale head_sha");
  }
  return {
    trusted: false,
    verdict: errors.length === 0 ? "untrusted" : "fail",
    errors: errors.sort(),
  };
}

export async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

export async function listFiles(root, predicate = () => true) {
  const result = [];
  async function walk(current) {
    const entries = await fs.readdir(current, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const resolved = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(resolved);
      else if (predicate(resolved)) result.push(resolved);
    }
  }
  await walk(root);
  return result;
}

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { normalizeRepoPath, validateTaskContract } from "./quality-contract.mjs";

function loadManifestToolSets() {
  try {
    const manifestPath = path.join(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../../.cursor/hooks/policy-manifest.json",
    );
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const toBase = (ids) =>
      new Set(
        (ids ?? []).map((id) =>
          String(id)
            .split(/[./]/)
            .at(-1)
            .toLowerCase(),
        ),
      );
    return {
      read: toBase(manifest.verified_tool_ids?.read),
      mutation: toBase(manifest.verified_tool_ids?.mutation),
      protected:
        manifest.protected_roots?.filter((root) => !root.startsWith("~")) ?? [
          ".git",
          ".github",
          "docs/prd",
          "src",
        ],
    };
  } catch {
    return {
      read: new Set(["readfile", "glob", "rg", "readlints"]),
      mutation: new Set([
        "applypatch",
        "write",
        "writefile",
        "strreplace",
        "delete",
        "editnotebook",
      ]),
      protected: [".git", ".github", "docs/prd", "src"],
    };
  }
}

const MANIFEST_TOOLS = loadManifestToolSets();
const READ_TOOLS = MANIFEST_TOOLS.read;
const MUTATION_TOOLS = MANIFEST_TOOLS.mutation;
const PROTECTED_PREFIXES = MANIFEST_TOOLS.protected;

function decision(verdict, reasonCode) {
  return Object.freeze({ verdict, reason_code: reasonCode });
}

function baseToolName(value) {
  return String(value ?? "")
    .split(/[./]/)
    .at(-1)
    .toLowerCase();
}

function pathMatches(candidate, pattern) {
  const normalizedPattern = normalizeRepoPath(pattern).replace(/\/\*\*$/, "");
  return (
    candidate === normalizedPattern ||
    candidate.startsWith(`${normalizedPattern}/`)
  );
}

function isProtectedPath(rawPath) {
  if (/^(?:[a-zA-Z]:\/|\/|~)/.test(rawPath.replaceAll("\\", "/"))) return true;
  const candidate = normalizeRepoPath(rawPath);
  if (
    PROTECTED_PREFIXES.some(
      (prefix) => candidate === prefix || candidate.startsWith(`${prefix}/`),
    )
  ) {
    return true;
  }
  if (
    candidate.startsWith("tests/") &&
    !candidate.startsWith("tests/quality/") &&
    !candidate.startsWith("tests/fixtures/quality/")
  ) {
    return true;
  }
  return false;
}

function decideMutation(contract, paths) {
  if (contract.profile === "read_only") {
    return decision("deny", "profile_read_only");
  }
  if (contract.approval.status !== "approved") {
    return decision("deny", "approval_required");
  }
  if (!Array.isArray(paths) || paths.length === 0) {
    return decision("deny", "mutation_path_missing");
  }
  for (const rawPath of paths) {
    let candidate;
    try {
      if (isProtectedPath(rawPath)) return decision("deny", "protected_scope");
      candidate = normalizeRepoPath(rawPath);
    } catch {
      return decision("deny", "path_parse_failed");
    }
    if (contract.denied_paths.some((pattern) => pathMatches(candidate, pattern))) {
      return decision("deny", "denied_path");
    }
    if (!contract.allowed_paths.some((pattern) => pathMatches(candidate, pattern))) {
      return decision("deny", "path_not_allowed");
    }
  }
  return decision("allow", "explicit_mutation_scope");
}

function decideShell(contract, command) {
  if (typeof command !== "string" || command.trim() === "") {
    return decision("deny", "shell_parse_failed");
  }
  const highRisk =
    /(?:-enc(?:odedcommand)?\b|frombase64string|invoke-expression|\biex\b|`|\$\(|;\s*(?:rm|del|git|invoke)|\bcmd(?:\.exe)?\s+\/c\b)/i;
  if (highRisk.test(command)) return decision("deny", "shell_high_risk");
  if (contract.required_checks.includes(command)) {
    return decision("allow", "required_check_exact_match");
  }
  return decision("ask", "shell_not_allowlisted");
}

function decideExternalTool(contract, action, namespace) {
  const identifier = `${action.server ?? namespace}/${action.tool ?? ""}`;
  if (contract.allowed_mcp_tools?.includes(identifier)) {
    return decision("allow", "external_tool_allowlisted");
  }
  return decision("ask", `${namespace}_unknown`);
}

export function evaluatePolicy(contract, action) {
  if (validateTaskContract(contract).length > 0) {
    return decision("deny", "task_contract_invalid");
  }
  if (!action || typeof action !== "object" || Array.isArray(action)) {
    return decision("deny", "action_parse_failed");
  }
  if (action.journal_state === "corrupt") {
    return action.kind === "read"
      ? decision("allow", "corrupt_journal_read_only")
      : decision("deny", "corrupt_journal_blocks_side_effects");
  }
  if (action.kind === "read") return decision("allow", "read_only_action");
  if (action.kind === "file_mutation") {
    return decideMutation(contract, action.paths);
  }
  if (action.kind === "shell") return decideShell(contract, action.command);
  if (action.kind === "mcp") return decideExternalTool(contract, action, "mcp");
  if (action.kind === "browser") {
    return decideExternalTool(contract, action, "browser");
  }
  if (action.kind === "tool") {
    const tool = baseToolName(action.tool_name);
    if (READ_TOOLS.has(tool)) return decision("allow", "known_read_tool");
    if (MUTATION_TOOLS.has(tool)) return decideMutation(contract, action.paths);
    return decision("deny", "unknown_tool");
  }
  return decision("deny", "unknown_action_kind");
}

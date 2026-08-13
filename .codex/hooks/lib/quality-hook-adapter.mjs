import fs from "node:fs/promises";
import path from "node:path";

import { ConversationJournal } from "../../../tools/quality/lib/conversation-journal.mjs";
import { evaluatePolicy } from "../../../tools/quality/lib/policy-engine.mjs";
import { sha256 } from "../../../tools/quality/lib/quality-contract.mjs";
import {
  eventCapability,
  featureFlag,
  isEventMapped,
  loadPolicyManifest,
} from "./policy-manifest.mjs";

const manifest = loadPolicyManifest();

export const VERIFIED_SHADOW_EVENTS = Object.freeze(
  Object.entries(manifest.events)
    .filter(([, meta]) => meta.runtime_verified === true && meta.mapped === true)
    .map(([eventName]) => eventName)
    .sort(),
);

const PREVENTIVE_EVENTS = new Set(
  Object.entries(manifest.events)
    .filter(([, meta]) => meta.capability_class === "preventive")
    .map(([eventName]) => eventName),
);

const TOOL_PATH_FIELDS = Object.freeze({
  ApplyPatch: [],
  "functions.ApplyPatch": [],
  Delete: ["path"],
  "functions.Delete": ["path"],
  EditNotebook: ["target_notebook"],
  "functions.EditNotebook": ["target_notebook"],
  StrReplace: ["path"],
  "functions.StrReplace": ["path"],
  Write: ["path"],
  WriteFile: ["path"],
  "functions.WriteFile": ["path"],
});

function shadowOutput(eventName) {
  // Feature flags come from policy-manifest.json (source of truth).
  // Shadow mode always allows; preventive deny is not armed while
  // feature_flags.preventive_enforcement is false.
  if (!featureFlag("preventive_enforcement") && PREVENTIVE_EVENTS.has(eventName)) {
    return { permission: "allow" };
  }
  if (PREVENTIVE_EVENTS.has(eventName)) {
    return { permission: "allow" };
  }
  return {};
}

function baselineContract(conversationId) {
  return {
    schema_version: "1.1.0",
    conversation_id: conversationId,
    task_id: "shadow-contract-missing",
    profile: "read_only",
    allowed_paths: [],
    denied_paths: [".git", ".github", "docs/prd", "src"],
    owner_documents: ["docs/engineering/LLM_ASSURANCE_MODEL.md"],
    requirement_ids: ["GOV-001", "GOV-005"],
    required_checks: [],
    approval: {
      status: "not_required",
      approved_by: null,
    },
    allowed_mcp_tools: [],
  };
}

function exactToolPaths(toolName, toolInput) {
  const fields = TOOL_PATH_FIELDS[toolName];
  if (!fields || !toolInput || typeof toolInput !== "object") return [];
  return fields.flatMap((field) =>
    typeof toolInput[field] === "string" ? [toolInput[field]] : [],
  );
}

function expectType(payload, field, types, diagnostics) {
  const value = payload[field];
  const actual = value === null ? "null" : Array.isArray(value) ? "array" : typeof value;
  if (!types.includes(actual)) diagnostics.push(`payload_type:${field}:${actual}`);
}

function validateObservedShape(eventName, payload) {
  const diagnostics = [];
  expectType(payload, "conversation_id", ["string"], diagnostics);
  expectType(payload, "cursor_version", ["string"], diagnostics);
  expectType(payload, "hook_event_name", ["string"], diagnostics);
  if (payload.hook_event_name !== eventName) diagnostics.push("hook_event_name_mismatch");
  if (payload.cursor_version !== "3.11.25") diagnostics.push("cursor_version_mismatch");

  if (eventName === "preToolUse" || eventName === "postToolUse") {
    expectType(payload, "tool_name", ["string"], diagnostics);
    expectType(payload, "tool_input", ["object"], diagnostics);
    expectType(payload, "tool_use_id", ["string"], diagnostics);
  } else if (
    eventName === "beforeShellExecution" ||
    eventName === "afterShellExecution"
  ) {
    expectType(payload, "command", ["string"], diagnostics);
  } else if (
    eventName === "beforeMCPExecution" ||
    eventName === "afterMCPExecution"
  ) {
    expectType(payload, "mcp_server_name", ["string"], diagnostics);
    expectType(payload, "tool_name", ["string"], diagnostics);
  } else if (eventName === "subagentStart") {
    expectType(payload, "tool_call_id", ["string"], diagnostics);
    expectType(payload, "subagent_id", ["string"], diagnostics);
    expectType(payload, "subagent_type", ["string"], diagnostics);
  } else if (eventName === "afterFileEdit") {
    expectType(payload, "file_path", ["string"], diagnostics);
    expectType(payload, "edits", ["array"], diagnostics);
  }
  return diagnostics;
}

export function mapVerifiedPayloadToAction(eventName, payload) {
  if (!isEventMapped(eventName) || !VERIFIED_SHADOW_EVENTS.includes(eventName)) {
    const meta = eventCapability(eventName);
    const reason = meta?.notes ?? "unverified event is not mapped";
    throw new TypeError(`unverified event is not mapped: ${eventName} (${reason})`);
  }
  if (eventName === "preToolUse" || eventName === "postToolUse") {
    return {
      kind: "tool",
      tool_name: payload.tool_name,
      paths: exactToolPaths(payload.tool_name, payload.tool_input),
    };
  }
  if (
    eventName === "beforeShellExecution" ||
    eventName === "afterShellExecution"
  ) {
    return { kind: "shell", command: payload.command };
  }
  if (
    eventName === "beforeMCPExecution" ||
    eventName === "afterMCPExecution"
  ) {
    return {
      kind: "mcp",
      server: payload.mcp_server_name,
      tool: payload.tool_name,
    };
  }
  if (eventName === "subagentStart") {
    return { kind: "tool", tool_name: "SubagentStart", paths: [] };
  }
  return { kind: "file_mutation", paths: [payload.file_path] };
}

async function editedFileEvidence(projectRoot, filePath) {
  if (typeof filePath !== "string" || filePath === "") return {};
  const resolved = path.resolve(projectRoot, filePath);
  const relative = path.relative(projectRoot, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return {};
  try {
    return {
      path: relative.replaceAll("\\", "/"),
      hash: sha256(await fs.readFile(resolved)),
    };
  } catch {
    return { path: relative.replaceAll("\\", "/") };
  }
}

export async function handleShadowEvent(
  eventName,
  payload,
  {
    projectRoot = process.env.CURSOR_PROJECT_DIR ?? process.cwd(),
    journalRoot =
      process.env.QUALITY_JOURNAL_DIR ??
      path.join(projectRoot, ".cursor", "quality-journals"),
    journal = new ConversationJournal(journalRoot),
  } = {},
) {
  const output = shadowOutput(eventName);
  const diagnostics = validateObservedShape(eventName, payload);
  if (typeof payload?.conversation_id !== "string" || payload.conversation_id === "") {
    return {
      output,
      shadow_verdict: "would_deny",
      reason_code: "contract_missing",
      diagnostics: [...diagnostics, "conversation_id_missing"].sort(),
      journal_appended: false,
    };
  }

  const contract = baselineContract(payload.conversation_id);
  const action = mapVerifiedPayloadToAction(eventName, payload);
  const policy = evaluatePolicy(contract, action);
  const details = {
    action: eventName,
    verdict: `would_${policy.verdict}`,
    reason: `contract_missing:${policy.reason_code}`,
  };
  if (typeof payload.tool_name === "string") details.tool = payload.tool_name;
  if (eventName === "afterFileEdit") {
    Object.assign(details, await editedFileEvidence(projectRoot, payload.file_path));
  }
  const stableInstanceId =
    eventName === "preToolUse" || eventName === "postToolUse"
      ? payload.tool_use_id
      : undefined;
  const eventType =
    eventName === "afterFileEdit"
      ? "edit"
      : eventName.startsWith("after") || eventName === "postToolUse"
        ? "tool"
        : "policy";
  try {
    const result = await journal.append(payload.conversation_id, {
      task_id: contract.task_id,
      event_type: eventType,
      stable_instance_id:
        typeof stableInstanceId === "string" && stableInstanceId !== ""
          ? stableInstanceId
          : undefined,
      details,
    });
    return {
      output,
      shadow_verdict: details.verdict,
      reason_code: policy.reason_code,
      diagnostics: diagnostics.sort(),
      journal_appended: result.appended,
    };
  } catch (error) {
    return {
      output,
      shadow_verdict: details.verdict,
      reason_code: policy.reason_code,
      diagnostics: [
        ...diagnostics,
        `journal_degraded:${error.name}`,
      ].sort(),
      journal_appended: false,
    };
  }
}

export async function runShadowHook(eventName) {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  let payload;
  try {
    payload = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    payload = {};
  }
  const result = await handleShadowEvent(eventName, payload);
  if (result.diagnostics.length > 0) {
    process.stderr.write(`${JSON.stringify({ event: eventName, diagnostics: result.diagnostics })}\n`);
  }
  process.stdout.write(JSON.stringify(result.output));
}

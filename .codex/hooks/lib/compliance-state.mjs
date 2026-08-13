import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/** @typedef {import("./compliance-state.mjs").ComplianceState} ComplianceState */

export function getStatePath() {
  if (process.env.COMPLIANCE_STATE_PATH) {
    return process.env.COMPLIANCE_STATE_PATH;
  }

  const projectDir = process.env.CURSOR_PROJECT_DIR;
  if (projectDir) {
    return path.join(projectDir, ".cursor", "session-compliance.json");
  }

  const cwd = process.cwd();
  if (cwd.endsWith(".cursor") || cwd.replace(/\\/g, "/").endsWith("/.cursor")) {
    return path.join(os.homedir(), ".cursor", "session-compliance.json");
  }

  return path.join(cwd, ".cursor", "session-compliance.json");
}

export function defaultState() {
  return {
    session_id: null,
    sequential_thinking_done: false,
    preflight_announced: false,
    complex: null,
    skills_declared: [],
    subagents_declared: [],
    subagents_used: [],
    sequential_thinking_calls: 0,
    last_sequential_thinking_at: null,
    started_at: new Date().toISOString(),
  };
}

export function readState() {
  const statePath = getStatePath();
  try {
    const raw = fs.readFileSync(statePath, "utf8");
    const parsed = JSON.parse(raw);
    return { ...defaultState(), ...parsed };
  } catch {
    return defaultState();
  }
}

export function writeState(patch) {
  const statePath = getStatePath();
  const dir = path.dirname(statePath);
  fs.mkdirSync(dir, { recursive: true });
  const next = { ...readState(), ...patch };
  fs.writeFileSync(statePath, JSON.stringify(next, null, 2));
  return next;
}

export function resetState(sessionId = null) {
  const state = {
    ...defaultState(),
    session_id: sessionId,
    started_at: new Date().toISOString(),
  };
  const statePath = getStatePath();
  const dir = path.dirname(statePath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
  return state;
}

export function markSequentialThinking() {
  const state = readState();
  return writeState({
    sequential_thinking_done: true,
    sequential_thinking_calls: (state.sequential_thinking_calls ?? 0) + 1,
    last_sequential_thinking_at: new Date().toISOString(),
  });
}

export function hasSequentialThinkingEvidence(state) {
  return (
    state.sequential_thinking_done === true ||
    (state.sequential_thinking_calls ?? 0) > 0
  );
}

export function isSequentialThinkingTool(input) {
  const haystack = JSON.stringify(input).toLowerCase();
  return (
    haystack.includes("sequential-thinking") ||
    haystack.includes("sequentialthinking")
  );
}

export function getToolName(input) {
  const candidates = [
    input.tool_name,
    input.toolName,
    input.tool,
    input.name,
    input.tool_type,
    input.toolType,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return "";
}

export async function readHookInput() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(typeof chunk === "string" ? chunk : chunk.toString("utf8"));
  }
  const raw = chunks.join("").trim();
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return { _raw: raw };
  }
}

export function emitHookResult(permission, extra = {}) {
  const payload =
    permission === "allow"
      ? { permission: "allow", ...extra }
      : {
          permission: "deny",
          agent_message: extra.agent_message ?? "Blocked by compliance hook.",
          user_message: extra.user_message ?? "Agent blocked: preflight required.",
          ...extra,
        };
  process.stdout.write(JSON.stringify(payload));
}

/**
 * @typedef {Object} ComplianceState
 * @property {string | null} session_id
 * @property {boolean} sequential_thinking_done
 * @property {boolean} preflight_announced
 * @property {boolean | null} complex
 * @property {string[]} skills_declared
 * @property {string[]} subagents_declared
 * @property {string[]} [subagents_used]
 * @property {number} [sequential_thinking_calls]
 * @property {string | null} [last_sequential_thinking_at]
 * @property {string} started_at
 */
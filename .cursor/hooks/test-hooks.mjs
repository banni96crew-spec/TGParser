/**
 * Manual hook tests for Phase B/C hook state sync.
 * Run: node .cursor/hooks/test-hooks.mjs
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..", "..");
const statePath = path.join(projectRoot, ".cursor", "session-compliance.json");
const tempStatePath = path.join(projectRoot, ".cursor", "session-compliance-test-temp.json");
const hooksDir = path.join(projectRoot, ".cursor", "hooks");

function runHook(script, input, env = {}) {
  const result = spawnSync(process.execPath, [path.join(hooksDir, script)], {
    input: JSON.stringify(input),
    encoding: "utf8",
    cwd: projectRoot,
    env: {
      ...process.env,
      CURSOR_PROJECT_DIR: projectRoot,
      COMPLIANCE_STATE_PATH: statePath,
      ...env,
    },
  });
  let parsed = {};
  try {
    parsed = JSON.parse(result.stdout.trim() || "{}");
  } catch {
    parsed = { _stdout: result.stdout, _stderr: result.stderr };
  }
  return { exitCode: result.status, output: parsed, stderr: result.stderr };
}

function reset() {
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        session_id: "test",
        sequential_thinking_done: false,
        preflight_announced: false,
        complex: null,
        skills_declared: [],
        subagents_declared: [],
        subagents_used: [],
        sequential_thinking_calls: 0,
        last_sequential_thinking_at: null,
        started_at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
}

function restoreLiveState() {
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        session_id: "restored-after-tests",
        sequential_thinking_done: true,
        sequential_thinking_calls: 1,
        last_sequential_thinking_at: new Date().toISOString(),
        preflight_announced: false,
        complex: null,
        skills_declared: [],
        subagents_declared: [],
        subagents_used: [],
        started_at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
}

let passed = 0;
let failed = 0;

function assert(name, condition, detail = "") {
  if (condition) {
    console.log(`PASS ${name}`);
    passed += 1;
  } else {
    console.error(`FAIL ${name}${detail ? `: ${detail}` : ""}`);
    failed += 1;
  }
}

reset();
const t1 = runHook("require-preflight.mjs", { tool_name: "Read", path: "package.json" });
assert("B-T1 deny Read without ST", t1.exitCode === 2 && t1.output.permission === "deny", JSON.stringify(t1.output));

reset();
fs.writeFileSync(
  statePath,
  JSON.stringify({
    session_id: "test",
    sequential_thinking_done: true,
    preflight_announced: false,
    complex: null,
    skills_declared: [],
    subagents_declared: [],
    subagents_used: [],
    sequential_thinking_calls: 1,
    last_sequential_thinking_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
  }),
);
const t2 = runHook("require-preflight.mjs", { tool_name: "Read", path: "package.json" });
assert("B-T2 allow Read after ST", t2.exitCode === 0 && t2.output.permission === "allow", JSON.stringify(t2.output));

reset();
runHook("mark-sequential-thinking.mjs", {
  server: "user-sequential-thinking",
  tool: "sequentialthinking",
});
const stateAfter = JSON.parse(fs.readFileSync(statePath, "utf8"));
assert("B-T3 mark ST sets flag", stateAfter.sequential_thinking_done === true, JSON.stringify(stateAfter));

reset();
const t4 = runHook("require-preflight.mjs", {
  server: "user-sequential-thinking",
  tool: "sequentialthinking",
});
const stateAfterPreTool = JSON.parse(fs.readFileSync(statePath, "utf8"));
assert(
  "B-T4 require-preflight marks ST tool",
  t4.exitCode === 0 &&
    t4.output.permission === "allow" &&
    stateAfterPreTool.sequential_thinking_done === true &&
    stateAfterPreTool.sequential_thinking_calls > 0,
  JSON.stringify({ output: t4.output, state: stateAfterPreTool }),
);

try {
  fs.unlinkSync(tempStatePath);
} catch {}
runHook("session-start.mjs", { session_id: "new-session" }, { COMPLIANCE_STATE_PATH: tempStatePath });
const stateReset = JSON.parse(fs.readFileSync(tempStatePath, "utf8"));
assert(
  "sessionStart resets ST flag",
  stateReset.sequential_thinking_done === false && stateReset.session_id === "new-session",
);
try {
  fs.unlinkSync(tempStatePath);
} catch {}

reset();
const t5 = runHook("require-preflight-subagent.mjs", { subagent_type: "explore" });
assert("subagent deny without ST", t5.exitCode === 2 && t5.output.permission === "deny");

restoreLiveState();
console.log("Restored live session state (sequential_thinking_done: true)");
console.log(`\nResults: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);

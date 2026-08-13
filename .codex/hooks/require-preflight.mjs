import {
  readHookInput,
  readState,
  isSequentialThinkingTool,
  markSequentialThinking,
  getToolName,
  emitHookResult,
} from "./lib/compliance-state.mjs";

const input = await readHookInput();
const toolName = getToolName(input);

if (isSequentialThinkingTool(input)) {
  markSequentialThinking();
  emitHookResult("allow");
  process.exit(0);
}

const gatedTools = new Set([
  "read",
  "grep",
  "glob",
  "shell",
  "task",
  "write",
  "strreplace",
  "delete",
  "editnotebook",
]);

const normalized = toolName.toLowerCase().replace(/[^a-z]/g, "");

if (!gatedTools.has(normalized) && !gatedTools.has(toolName.toLowerCase())) {
  const haystack = JSON.stringify(input).toLowerCase();
  const matchesGated = [...gatedTools].some((tool) => haystack.includes(tool));
  if (!matchesGated) {
    emitHookResult("allow");
    process.exit(0);
  }
}

const state = readState();
if (!state.sequential_thinking_done) {
  emitHookResult("deny", {
    agent_message:
      "00-agent-preflight: call user-sequential-thinking/sequentialthinking before any Read/Grep/Glob/Shell/Task/Write/StrReplace/Delete/EditNotebook.",
    user_message: "Agent blocked: preflight required.",
  });
  process.exit(2);
}

emitHookResult("allow");
process.exit(0);

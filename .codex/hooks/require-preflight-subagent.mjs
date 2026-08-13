import {
  readHookInput,
  readState,
  writeState,
  emitHookResult,
} from "./lib/compliance-state.mjs";

const input = await readHookInput();
const state = readState();

if (!state.sequential_thinking_done) {
  emitHookResult("deny", {
    agent_message:
      "00-agent-preflight: call user-sequential-thinking/sequentialthinking before starting subagents.",
    user_message: "Agent blocked: preflight required before subagent.",
  });
  process.exit(2);
}

const subagentType =
  typeof input.subagent_type === "string"
    ? input.subagent_type
    : typeof input.subagentType === "string"
      ? input.subagentType
      : typeof input.type === "string"
        ? input.type
        : null;

if (
  state.complex === true &&
  state.subagents_declared.length > 0 &&
  subagentType &&
  !state.subagents_declared.includes(subagentType)
) {
  emitHookResult("deny", {
    agent_message: `00-agent-preflight: subagent "${subagentType}" was not declared in Pre-flight. Declared: ${state.subagents_declared.join(", ")}.`,
    user_message: "Agent blocked: undeclared subagent.",
  });
  process.exit(2);
}

if (subagentType) {
  writeState({
    subagents_used: [...new Set([...(state.subagents_used ?? []), subagentType])],
  });
}

emitHookResult("allow");
process.exit(0);

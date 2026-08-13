import {
  readHookInput,
  isSequentialThinkingTool,
  markSequentialThinking,
  emitHookResult,
} from "./lib/compliance-state.mjs";

const input = await readHookInput();

if (isSequentialThinkingTool(input)) {
  markSequentialThinking();
}

emitHookResult("allow");
process.exit(0);

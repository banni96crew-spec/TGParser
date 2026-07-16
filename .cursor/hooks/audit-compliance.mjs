import { readState, hasSequentialThinkingEvidence, emitHookResult } from "./lib/compliance-state.mjs";

const state = readState();
const failures = [];

if (!hasSequentialThinkingEvidence(state)) {
  failures.push("sequential-thinking was not completed (no MCP call detected)");
}

if (state.complex === true && state.skills_declared.length > 0) {
  // Declared skills exist — informational only at stop; agent reports in Compliance block
}

if (failures.length > 0) {
  emitHookResult("allow", {
    followup_message: [
      "Compliance audit failed:",
      ...failures.map((f) => `- ${f}`),
      "",
      "Print a ### Compliance block with pass|fail per item per 00-agent-preflight.mdc.",
    ].join("\n"),
  });
  process.exit(0);
}

emitHookResult("allow");
process.exit(0);

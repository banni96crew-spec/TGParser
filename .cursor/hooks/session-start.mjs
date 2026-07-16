import {
  readHookInput,
  resetState,
  emitHookResult,
} from "./lib/compliance-state.mjs";

const input = await readHookInput();
const sessionId =
  typeof input.session_id === "string"
    ? input.session_id
    : typeof input.conversation_id === "string"
      ? input.conversation_id
      : null;

resetState(sessionId);
emitHookResult("allow");
process.exit(0);

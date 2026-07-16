import {
  readState,
  hasSequentialThinkingEvidence,
  emitHookResult,
  readHookInput,
} from "./lib/compliance-state.mjs";
import fs from "node:fs";
import path from "node:path";
import { featureFlag, loadPolicyManifest } from "./lib/policy-manifest.mjs";

const manifest = loadPolicyManifest();
const input = await readHookInput();
const state = readState();
const failures = [];
const advisories = [];

if (!hasSequentialThinkingEvidence(state)) {
  failures.push("sequential-thinking was not completed (no MCP call detected)");
}

const projectDir = process.env.CURSOR_PROJECT_DIR ?? process.cwd();
const conversationId =
  typeof input.conversation_id === "string" && input.conversation_id !== ""
    ? input.conversation_id
    : state.session_id;

if (featureFlag("evidence_claims", manifest) && conversationId) {
  const claimsDir =
    process.env.QUALITY_CLAIMS_DIR ??
    path.join(projectDir, ".cursor", "quality-claims");
  let hasClaim = false;
  try {
    const entries = fs.readdirSync(claimsDir);
    hasClaim = entries.some((name) => name.endsWith(".json"));
  } catch {
    hasClaim = false;
  }
  if (!hasClaim) {
    advisories.push(
      "No local evidence claim under .cursor/quality-claims/ (untrusted claims are advisory; record via tools/quality checkpoint).",
    );
  }
}

const journalDir =
  process.env.QUALITY_JOURNAL_DIR ??
  path.join(projectDir, ".cursor", "quality-journals");
try {
  const entries = fs.readdirSync(journalDir);
  const dirtyTemp = entries.some(
    (name) => name.endsWith(".tmp") || name.endsWith(".lock"),
  );
  if (dirtyTemp) {
    advisories.push(
      "Conversation journal has dirty temp/lock files; verify journal integrity before trusting local evidence.",
    );
  }
} catch {
  // missing journal root is fine in shadow mode
}

// stop remains allow — never a hard completion gate (policy-manifest feature_flags).
const hardGate = manifest.events?.stop?.hard_completion_gate === true;
if (hardGate) {
  // Reserved for future preventive mode; currently disabled by manifest.
}

const messages = [];
if (failures.length > 0) {
  messages.push("Compliance audit notes:");
  messages.push(...failures.map((item) => `- ${item}`));
}
if (advisories.length > 0) {
  if (messages.length === 0) messages.push("Quality advisory:");
  messages.push(...advisories.map((item) => `- ${item}`));
}
if (messages.length > 0) {
  messages.push("");
  messages.push(
    "Evidence claim (AT-GOV-007) outweighs self-reported ### Compliance text. Always allow stop; print ### Compliance with pass|fail|not_run.",
  );
  emitHookResult("allow", {
    followup_message: messages.join("\n"),
  });
  process.exit(0);
}

emitHookResult("allow");
process.exit(0);

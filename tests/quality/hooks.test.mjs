import assert from "node:assert/strict";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  VERIFIED_SHADOW_EVENTS,
  handleShadowEvent,
  mapVerifiedPayloadToAction,
} from "../../.cursor/hooks/lib/quality-hook-adapter.mjs";
import { ConversationJournal } from "../../tools/quality/lib/conversation-journal.mjs";

const root = path.resolve(".");
const fixtureNames = {
  preToolUse: "pre-tool-use.json",
  postToolUse: "post-tool-use.json",
  beforeShellExecution: "before-shell-execution.json",
  afterShellExecution: "after-shell-execution.json",
  beforeMCPExecution: "before-mcp-execution.json",
  afterMCPExecution: "after-mcp-execution.json",
  subagentStart: "subagent-start.json",
  afterFileEdit: "after-file-edit.json",
};
const common = {
  conversation_id: "conversation-shadow",
  cursor_version: "3.11.25",
  generation_id: "generation-test",
  hook_event_name: "",
  model: "test-model",
  session_id: "session-test",
  transcript_path: null,
  user_email: "fixture@example.invalid",
  workspace_roots: [root],
};

function payloads() {
  return {
    preToolUse: {
      ...common,
      cwd: root,
      hook_event_name: "preToolUse",
      tool_input: { path: "docs/engineering/README.md" },
      tool_name: "ReadFile",
      tool_use_id: "tool-use-pre",
    },
    postToolUse: {
      ...common,
      cwd: root,
      duration: 1,
      hook_event_name: "postToolUse",
      tool_input: { path: "docs/engineering/README.md" },
      tool_name: "ReadFile",
      tool_output: "synthetic",
      tool_use_id: "tool-use-post",
    },
    beforeShellExecution: {
      ...common,
      command: "node --version",
      cwd: root,
      hook_event_name: "beforeShellExecution",
      sandbox: true,
    },
    afterShellExecution: {
      ...common,
      command: "node --version",
      duration: 1,
      hook_event_name: "afterShellExecution",
      output: "synthetic",
      sandbox: true,
    },
    beforeMCPExecution: {
      ...common,
      command: "synthetic",
      hook_event_name: "beforeMCPExecution",
      mcp_server_name: "unknown-server",
      tool_input: "{}",
      tool_name: "unknown-tool",
    },
    afterMCPExecution: {
      ...common,
      duration: 1,
      hook_event_name: "afterMCPExecution",
      mcp_server_name: "unknown-server",
      result_json: "{}",
      tool_input: "{}",
      tool_name: "unknown-tool",
    },
    subagentStart: {
      ...common,
      hook_event_name: "subagentStart",
      is_parallel_worker: false,
      parent_conversation_id: "parent-conversation",
      subagent_id: "subagent-test",
      subagent_model: "test-model",
      subagent_type: "explore",
      task: "synthetic task",
      tool_call_id: "tool-call-visible-not-stable",
      transcript_path: "synthetic-transcript",
    },
    afterFileEdit: {
      ...common,
      edits: [],
      file_path: "synthetic.txt",
      hook_event_name: "afterFileEdit",
    },
  };
}

function describe(value) {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

async function tempProject(t) {
  const projectRoot = await fs.mkdtemp(path.join(os.tmpdir(), "quality-hooks-"));
  t.after(() => fs.rm(projectRoot, { recursive: true, force: true }));
  const journalRoot = path.join(projectRoot, ".cursor", "quality-journals");
  return { projectRoot, journalRoot };
}

test("synthetic payload fixtures exactly match sanitized verified shapes", async () => {
  const allPayloads = payloads();
  assert.deepEqual([...VERIFIED_SHADOW_EVENTS].sort(), Object.keys(allPayloads).sort());
  for (const eventName of VERIFIED_SHADOW_EVENTS) {
    const fixture = JSON.parse(
      await fs.readFile(
        path.join(
          root,
          "tests",
          "fixtures",
          "quality",
          "capabilities",
          fixtureNames[eventName],
        ),
        "utf8",
      ),
    );
    const verified = fixture.runtime_payload_verification.verified_fields;
    for (const [key, value] of Object.entries(allPayloads[eventName])) {
      assert.ok(key in verified, `${eventName} missing fixture field ${key}`);
      assert.ok(
        verified[key].includes(describe(value)),
        `${eventName}.${key} type ${describe(value)} not in ${verified[key]}`,
      );
    }
    for (const key of Object.keys(verified)) {
      assert.ok(
        key in allPayloads[eventName],
        `${eventName} synthetic payload missing observed field ${key}`,
      );
    }
    assert.equal(fixture.status, "runtime_verified");
    assert.equal(fixture.runtime_payload_verification.support_status, "verified");
    assert.equal(fixture.runtime_payload_verification.execution_status, "observed");
    assert.equal(fixture.runtime_payload_verification.cursor_version, "3.11.25");
  }
});

test("exact mapper rejects unverified events", () => {
  assert.throws(
    () => mapVerifiedPayloadToAction("afterTabFileEdit", {}),
    /unverified event/,
  );
  assert.throws(() => mapVerifiedPayloadToAction("stop", {}), /unverified event/);
  assert.throws(
    () => mapVerifiedPayloadToAction("sessionStart", {}),
    /unverified event/,
  );
});

test("shadow mode records would verdicts but always allows preventive events", async (t) => {
  const { projectRoot, journalRoot } = await tempProject(t);
  const allPayloads = payloads();
  const readResult = await handleShadowEvent("preToolUse", allPayloads.preToolUse, {
    projectRoot,
    journalRoot,
  });
  assert.deepEqual(readResult.output, { permission: "allow" });
  assert.equal(readResult.shadow_verdict, "would_allow");

  const mutationPayload = {
    ...allPayloads.preToolUse,
    tool_input: {},
    tool_name: "ApplyPatch",
    tool_use_id: "tool-use-mutation",
  };
  const mutationResult = await handleShadowEvent("preToolUse", mutationPayload, {
    projectRoot,
    journalRoot,
  });
  assert.deepEqual(mutationResult.output, { permission: "allow" });
  assert.equal(mutationResult.shadow_verdict, "would_deny");
  assert.equal(mutationResult.reason_code, "profile_read_only");

  const shellResult = await handleShadowEvent(
    "beforeShellExecution",
    allPayloads.beforeShellExecution,
    { projectRoot, journalRoot },
  );
  assert.deepEqual(shellResult.output, { permission: "allow" });
  assert.equal(shellResult.shadow_verdict, "would_ask");
});

test("missing trusted contract is explicit and stable tool IDs deduplicate", async (t) => {
  const { projectRoot, journalRoot } = await tempProject(t);
  const payload = payloads().preToolUse;
  const first = await handleShadowEvent("preToolUse", payload, {
    projectRoot,
    journalRoot,
  });
  const second = await handleShadowEvent("preToolUse", payload, {
    projectRoot,
    journalRoot,
  });
  assert.equal(first.journal_appended, true);
  assert.equal(second.journal_appended, false);
  const journal = new ConversationJournal(journalRoot);
  const events = (await journal.read(payload.conversation_id)).events;
  assert.equal(events.length, 1);
  assert.match(events[0].details.reason, /^contract_missing:/);
});

test("afterFileEdit records repository-relative path and SHA-256", async (t) => {
  const { projectRoot, journalRoot } = await tempProject(t);
  const relative = path.join("данные", "файл.txt");
  const absolute = path.join(projectRoot, relative);
  await fs.mkdir(path.dirname(absolute), { recursive: true });
  await fs.writeFile(absolute, "synthetic edit", "utf8");
  const payload = {
    ...payloads().afterFileEdit,
    file_path: absolute,
  };
  const result = await handleShadowEvent("afterFileEdit", payload, {
    projectRoot,
    journalRoot,
  });
  assert.deepEqual(result.output, {});
  assert.equal(result.shadow_verdict, "would_deny");
  const journal = new ConversationJournal(journalRoot);
  const [edit] = (await journal.read(payload.conversation_id)).events;
  assert.equal(edit.event_type, "edit");
  assert.equal(edit.details.path, "данные/файл.txt");
  assert.equal(
    edit.details.hash,
    crypto.createHash("sha256").update("synthetic edit").digest("hex"),
  );
});

test("corrupt journal degrades diagnostics without blocking", async (t) => {
  const { projectRoot, journalRoot } = await tempProject(t);
  const payload = payloads().preToolUse;
  const journal = new ConversationJournal(journalRoot);
  const journalPath = journal.pathsFor(payload.conversation_id).journal;
  await fs.mkdir(journalRoot, { recursive: true });
  await fs.writeFile(journalPath, '{"truncated":', "utf8");
  const result = await handleShadowEvent("preToolUse", payload, {
    projectRoot,
    journalRoot,
  });
  assert.deepEqual(result.output, { permission: "allow" });
  assert.equal(result.journal_appended, false);
  assert.ok(
    result.diagnostics.some((item) =>
      item.startsWith("journal_degraded:JournalCorruptionError"),
    ),
  );
});

test("runtime wrapper uses temp journal and never touches live compliance state", async (t) => {
  const { projectRoot, journalRoot } = await tempProject(t);
  const liveState = path.join(root, ".cursor", "session-compliance.json");
  const before = await fs.readFile(liveState);
  const payload = payloads().beforeShellExecution;
  const child = spawn(
    process.execPath,
    [path.join(root, ".cursor", "hooks", "quality-before-shell-execution.mjs")],
    {
      cwd: root,
      env: {
        ...process.env,
        CURSOR_PROJECT_DIR: projectRoot,
        QUALITY_JOURNAL_DIR: journalRoot,
      },
      windowsHide: true,
    },
  );
  child.stdin.end(JSON.stringify(payload));
  let stdout = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  const exitCode = await new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("close", resolve);
  });
  assert.equal(exitCode, 0);
  assert.deepEqual(JSON.parse(stdout), { permission: "allow" });
  assert.deepEqual(await fs.readFile(liveState), before);
});

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  ConversationJournal,
  JournalCorruptionError,
} from "../../tools/quality/lib/conversation-journal.mjs";

async function temporaryDirectory(t, suffix = "") {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), `quality-${suffix}`));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}

function event(sequence, overrides = {}) {
  return {
    task_id: "task-journal",
    event_type: "tool",
    details: { sequence },
    ...overrides,
  };
}

test("four parallel sessions retain 100 isolated events each", async (t) => {
  const root = await temporaryDirectory(t, "parallel-");
  const journal = new ConversationJournal(root);
  const sessions = ["session-a", "session-b", "session-c", "session-d"];
  await Promise.all(
    sessions.map(async (session) => {
      for (let index = 0; index < 100; index += 1) {
        await journal.append(session, event(index));
      }
    }),
  );
  for (const session of sessions) {
    const result = await journal.read(session);
    assert.equal(result.state, "healthy");
    assert.equal(result.events.length, 100);
    assert.ok(result.events.every((item) => item.conversation_id === session));
  }
});

test("100 concurrent same-session events have zero loss", async (t) => {
  const root = await temporaryDirectory(t, "same-");
  const journal = new ConversationJournal(root);
  await Promise.all(
    Array.from({ length: 100 }, (_, index) =>
      journal.append("same-session", event(index)),
    ),
  );
  const result = await journal.read("same-session");
  assert.equal(result.state, "healthy");
  assert.equal(result.events.length, 100);
  assert.equal(new Set(result.events.map((item) => item.event_id)).size, 100);
});

test("stable instance ID is exactly-once while missing ID is never deduplicated", async (t) => {
  const root = await temporaryDirectory(t, "dedupe-");
  const journal = new ConversationJournal(root);
  const duplicateResults = await Promise.all(
    Array.from({ length: 20 }, () =>
      journal.append(
        "duplicate-session",
        event(1, { stable_instance_id: "tool-use-1" }),
      ),
    ),
  );
  assert.equal(
    duplicateResults.filter((result) => result.appended).length,
    1,
  );
  await journal.append("duplicate-session", event(2));
  await journal.append("duplicate-session", event(2));
  const result = await journal.read("duplicate-session");
  assert.equal(result.events.length, 3);
});

test("delayed sessionStart is irrelevant and Cyrillic paths are safe", async (t) => {
  const parent = await temporaryDirectory(t, "unicode-");
  const root = path.join(parent, "Тест проект", "журналы");
  const journal = new ConversationJournal(root);
  const conversation = "  Разговор № 1  ";
  const appended = await journal.append(conversation, event(1));
  assert.equal(path.basename(appended.path).length, 70);
  assert.doesNotMatch(path.basename(appended.path), /Разговор/);
  const result = await journal.read("Разговор № 1");
  assert.equal(result.events.length, 1);
});

test("malformed and truncated journals degrade without silent reset", async (t) => {
  const root = await temporaryDirectory(t, "corrupt-");
  const journal = new ConversationJournal(root);
  const malformed = journal.pathsFor("malformed");
  const truncated = journal.pathsFor("truncated");
  await fs.mkdir(root, { recursive: true });
  await fs.writeFile(malformed.journal, '{"broken":\n', "utf8");
  await fs.writeFile(truncated.journal, '{"schema_version":"1.1.0"}', "utf8");

  assert.equal((await journal.read("malformed")).state, "degraded");
  assert.equal((await journal.read("truncated")).state, "degraded");
  await assert.rejects(
    journal.append("malformed", event(1)),
    JournalCorruptionError,
  );
  assert.equal(await fs.readFile(malformed.journal, "utf8"), '{"broken":\n');
});

test("stale lock is preserved as evidence and safely replaced", async (t) => {
  const root = await temporaryDirectory(t, "stale-");
  const journal = new ConversationJournal(root, {
    lockTimeoutMs: 500,
    staleLockMs: 5,
    retryDelayMs: 1,
  });
  const paths = journal.pathsFor("stale-session");
  await fs.mkdir(paths.lock, { recursive: true });
  await fs.writeFile(
    path.join(paths.lock, "owner.json"),
    JSON.stringify({
      token: "abandoned",
      pid: 2147483647,
      hostname: os.hostname(),
    }),
  );
  const old = new Date(Date.now() - 60_000);
  await fs.utimes(paths.lock, old, old);
  await journal.append("stale-session", event(1));
  const entries = await fs.readdir(root);
  assert.ok(entries.some((name) => name.startsWith(`${paths.digest}.lock.stale-`)));
  assert.equal((await journal.read("stale-session")).events.length, 1);
});

test("interrupted unique temp is retained and does not corrupt journal", async (t) => {
  const root = await temporaryDirectory(t, "temp-");
  const journal = new ConversationJournal(root);
  const paths = journal.pathsFor("temp-session");
  await fs.mkdir(root, { recursive: true });
  const interrupted = `${paths.journal}.interrupted.tmp`;
  await fs.writeFile(interrupted, '{"partial":', "utf8");
  await journal.append("temp-session", event(1));
  assert.equal((await journal.read("temp-session")).state, "healthy");
  assert.equal(await fs.readFile(interrupted, "utf8"), '{"partial":');
});

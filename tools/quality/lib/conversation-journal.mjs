import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  CONTRACT_VERSION,
  JOURNAL_EVENT_TYPES,
  normalizeConversationId,
  sha256,
} from "./quality-contract.mjs";

export class JournalLockTimeoutError extends Error {
  constructor(message) {
    super(message);
    this.name = "JournalLockTimeoutError";
  }
}

export class JournalCorruptionError extends Error {
  constructor(message, diagnostics) {
    super(message);
    this.name = "JournalCorruptionError";
    this.diagnostics = diagnostics;
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function processIsAlive(owner) {
  if (
    !owner ||
    owner.hostname !== os.hostname() ||
    !Number.isInteger(owner.pid) ||
    owner.pid <= 0
  ) {
    return false;
  }
  try {
    process.kill(owner.pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

export class ConversationJournal {
  constructor(
    rootDirectory,
    {
      lockTimeoutMs = 2_000,
      staleLockMs = 30_000,
      retryDelayMs = 2,
      now = () => Date.now(),
    } = {},
  ) {
    this.rootDirectory = rootDirectory;
    this.lockTimeoutMs = lockTimeoutMs;
    this.staleLockMs = staleLockMs;
    this.retryDelayMs = retryDelayMs;
    this.now = now;
    this.localQueues = new Map();
  }

  pathsFor(conversationId) {
    const normalized = normalizeConversationId(conversationId);
    const digest = sha256(normalized);
    return {
      normalized,
      digest,
      journal: path.join(this.rootDirectory, `${digest}.jsonl`),
      lock: path.join(this.rootDirectory, `${digest}.lock`),
    };
  }

  async #recoverStaleLock(paths) {
    let stat;
    try {
      stat = await fs.stat(paths.lock);
    } catch (error) {
      if (error.code === "ENOENT") return false;
      throw error;
    }
    if (this.now() - stat.mtimeMs <= this.staleLockMs) return false;

    let owner = null;
    try {
      owner = JSON.parse(
        await fs.readFile(path.join(paths.lock, "owner.json"), "utf8"),
      );
    } catch {
      owner = null;
    }
    if (await processIsAlive(owner)) return false;

    const evidencePath = `${paths.lock}.stale-${this.now()}-${crypto.randomUUID()}`;
    try {
      await fs.rename(paths.lock, evidencePath);
      return true;
    } catch (error) {
      if (error.code === "ENOENT") return false;
      throw error;
    }
  }

  async #acquire(paths) {
    await fs.mkdir(this.rootDirectory, { recursive: true });
    const owner = {
      token: crypto.randomUUID(),
      pid: process.pid,
      hostname: os.hostname(),
      acquired_at: new Date(this.now()).toISOString(),
    };
    const deadline = this.now() + this.lockTimeoutMs;
    while (this.now() <= deadline) {
      try {
        await fs.mkdir(paths.lock);
        await fs.writeFile(
          path.join(paths.lock, "owner.json"),
          `${JSON.stringify(owner)}\n`,
          { encoding: "utf8", flag: "wx" },
        );
        return owner;
      } catch (error) {
        if (error.code !== "EEXIST") throw error;
        await this.#recoverStaleLock(paths);
        await sleep(this.retryDelayMs);
      }
    }
    throw new JournalLockTimeoutError(
      `journal lock not acquired within ${this.lockTimeoutMs}ms`,
    );
  }

  async #release(paths, owner) {
    let current;
    try {
      current = JSON.parse(
        await fs.readFile(path.join(paths.lock, "owner.json"), "utf8"),
      );
    } catch (error) {
      throw new JournalLockTimeoutError(
        `journal lock ownership cannot be verified: ${error.message}`,
      );
    }
    if (current.token !== owner.token) {
      throw new JournalLockTimeoutError("journal lock owner changed");
    }
    await fs.rm(paths.lock, { recursive: true });
  }

  async read(conversationId) {
    const paths = this.pathsFor(conversationId);
    let text;
    try {
      text = await fs.readFile(paths.journal, "utf8");
    } catch (error) {
      if (error.code === "ENOENT") {
        return { state: "healthy", events: [], diagnostics: [], path: paths.journal };
      }
      throw error;
    }
    const diagnostics = [];
    if (text !== "" && !text.endsWith("\n")) {
      diagnostics.push({
        code: "truncated_tail",
        line: text.split("\n").length,
      });
    }
    const lines = text.split("\n");
    if (lines.at(-1) === "") lines.pop();
    const events = [];
    for (let index = 0; index < lines.length; index += 1) {
      try {
        events.push(JSON.parse(lines[index]));
      } catch (error) {
        diagnostics.push({
          code: "malformed_json",
          line: index + 1,
          message: error.message,
        });
      }
    }
    return {
      state: diagnostics.length === 0 ? "healthy" : "degraded",
      events,
      diagnostics,
      path: paths.journal,
    };
  }

  async append(conversationId, input) {
    const paths = this.pathsFor(conversationId);
    const previous = this.localQueues.get(paths.digest) ?? Promise.resolve();
    let releaseTurn;
    const turn = new Promise((resolve) => {
      releaseTurn = resolve;
    });
    const tail = previous.catch(() => {}).then(() => turn);
    this.localQueues.set(paths.digest, tail);
    await previous.catch(() => {});
    try {
      return await this.#appendLocked(paths, input);
    } finally {
      releaseTurn();
      if (this.localQueues.get(paths.digest) === tail) {
        this.localQueues.delete(paths.digest);
      }
    }
  }

  async #appendLocked(paths, input) {
    const owner = await this.#acquire(paths);
    try {
      const current = await this.read(paths.normalized);
      if (current.state !== "healthy") {
        throw new JournalCorruptionError(
          "journal is degraded; append refused without reset",
          current.diagnostics,
        );
      }
      if (!JOURNAL_EVENT_TYPES.includes(input?.event_type)) {
        throw new TypeError("event_type is unsupported");
      }
      if (typeof input.task_id !== "string" || input.task_id === "") {
        throw new TypeError("task_id must be a non-empty string");
      }
      const stableId =
        typeof input.stable_instance_id === "string" &&
        input.stable_instance_id !== ""
          ? input.stable_instance_id
          : null;
      const idempotencyKey = stableId
        ? sha256(`${input.event_type}\0${stableId}`)
        : null;
      if (idempotencyKey) {
        const duplicate = current.events.find(
          (event) => event.idempotency_key === idempotencyKey,
        );
        if (duplicate) return { appended: false, event: duplicate, path: paths.journal };
      }

      const event = {
        schema_version: CONTRACT_VERSION,
        event_id: crypto.randomUUID(),
        conversation_id: paths.normalized,
        task_id: input.task_id,
        event_type: input.event_type,
        occurred_at: input.occurred_at ?? new Date(this.now()).toISOString(),
        actor: input.actor ?? "llm_agent",
        details: input.details ?? {},
      };
      if (stableId) {
        event.stable_instance_id = stableId;
        event.idempotency_key = idempotencyKey;
      }
      const text = `${current.events.map((item) => JSON.stringify(item)).join("\n")}${
        current.events.length > 0 ? "\n" : ""
      }${JSON.stringify(event)}\n`;
      const temporary = `${paths.journal}.${owner.token}.tmp`;
      const handle = await fs.open(temporary, "wx");
      try {
        await handle.writeFile(text, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await fs.rename(temporary, paths.journal);
      return { appended: true, event, path: paths.journal };
    } finally {
      await this.#release(paths, owner);
    }
  }
}

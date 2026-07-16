#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  CONTRACT_VERSION,
  JOURNAL_EVENT_TYPES,
  canonicalJson,
} from "./lib/quality-contract.mjs";

export function validateJournalText(text, source = "<memory>") {
  const errors = [];
  const events = [];
  if (text !== "" && !text.endsWith("\n")) {
    errors.push(`${source}: truncated tail`);
  }
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const seenEvents = new Set();
  const seenIdempotency = new Set();
  for (let index = 0; index < lines.length; index += 1) {
    let event;
    try {
      event = JSON.parse(lines[index]);
    } catch {
      errors.push(`${source}:${index + 1}: malformed JSON`);
      continue;
    }
    events.push(event);
    if (event.schema_version !== CONTRACT_VERSION) {
      errors.push(`${source}:${index + 1}: schema_version mismatch`);
    }
    for (const field of [
      "event_id",
      "conversation_id",
      "task_id",
      "event_type",
      "occurred_at",
      "actor",
      "details",
    ]) {
      if (!(field in event)) errors.push(`${source}:${index + 1}: missing ${field}`);
    }
    if (!JOURNAL_EVENT_TYPES.includes(event.event_type)) {
      errors.push(`${source}:${index + 1}: unsupported event_type`);
    }
    if (seenEvents.has(event.event_id)) {
      errors.push(`${source}:${index + 1}: duplicate event_id`);
    }
    seenEvents.add(event.event_id);
    if (event.stable_instance_id && !event.idempotency_key) {
      errors.push(`${source}:${index + 1}: stable ID without idempotency key`);
    }
    if (event.idempotency_key) {
      if (seenIdempotency.has(event.idempotency_key)) {
        errors.push(`${source}:${index + 1}: duplicate idempotency key`);
      }
      seenIdempotency.add(event.idempotency_key);
    }
  }
  return { errors: errors.sort(), event_count: events.length };
}

export async function validateJournalFiles(filePaths) {
  const files = [];
  const errors = [];
  for (const filePath of [...filePaths].sort()) {
    const text = await fs.readFile(filePath, "utf8");
    const result = validateJournalText(text, filePath);
    files.push({ path: filePath, event_count: result.event_count });
    errors.push(...result.errors);
  }
  return {
    schema_version: "1.0.0",
    validator: "validate-journal",
    status: errors.length === 0 ? "pass" : "fail",
    errors: errors.sort(),
    files,
  };
}

async function main() {
  const filePaths = process.argv.slice(2).map((item) => path.resolve(item));
  if (filePaths.length === 0) {
    process.stderr.write("validate-journal requires at least one JSONL path\n");
    process.exitCode = 2;
    return;
  }
  const result = await validateJournalFiles(filePaths);
  process.stdout.write(canonicalJson(result));
  if (result.status !== "pass") process.exitCode = 1;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  await main();
}

#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  canonicalJson,
  canonicalize,
  listFiles,
  readJson,
} from "./lib/quality-contract.mjs";

const VERIFIED_EVENTS = new Set([
  "preToolUse",
  "postToolUse",
  "beforeShellExecution",
  "afterShellExecution",
  "beforeMCPExecution",
  "afterMCPExecution",
  "subagentStart",
  "afterFileEdit",
]);
const UNOBSERVED_EVENTS = new Set([
  "sessionStart",
  "afterTabFileEdit",
  "stop",
]);
const VERIFIED_PREVENTIVE_EVENTS = new Set([
  "preToolUse",
  "beforeShellExecution",
  "beforeMCPExecution",
  "subagentStart",
]);

function aggregateSpike(text) {
  const events = new Map();
  for (const line of text.split(/\r?\n/).filter(Boolean)) {
    const record = JSON.parse(line);
    const current = events.get(record.event) ?? {
      count: 0,
      verified_fields: {},
    };
    current.count += 1;
    for (const [field, type] of Object.entries(record.input_shape ?? {})) {
      const types = new Set(current.verified_fields[field] ?? []);
      types.add(type);
      current.verified_fields[field] = [...types].sort();
    }
    events.set(record.event, current);
  }
  return events;
}

export async function validateCapabilities(root = process.cwd()) {
  const errors = [];
  const hooksPath = path.join(root, ".cursor", "hooks.json");
  const fixturesRoot = path.join(
    root,
    "tests",
    "fixtures",
    "quality",
    "capabilities",
  );
  const hooks = await readJson(hooksPath);
  const spikePath = path.join(root, ".cursor", "quality-spike", "events.jsonl");
  const spikeText = await fs.readFile(spikePath, "utf8");
  const spikeHash = crypto.createHash("sha256").update(spikeText).digest("hex");
  const spike = aggregateSpike(spikeText);
  const fixturePaths = await listFiles(fixturesRoot, (file) => file.endsWith(".json"));
  const fixtures = await Promise.all(fixturePaths.map(readJson));
  const fixtureByEvent = new Map();
  for (const fixture of fixtures) {
    if (fixtureByEvent.has(fixture.event_key)) {
      errors.push(`duplicate fixture event_key: ${fixture.event_key}`);
    }
    fixtureByEvent.set(fixture.event_key, fixture);
    if (fixture.source?.path !== ".cursor/hooks.json") {
      errors.push(`invalid source path: ${fixture.event_key}`);
    }
    const runtime = fixture.runtime_payload_verification ?? {};
    if (VERIFIED_EVENTS.has(fixture.event_key)) {
      const observed = spike.get(fixture.event_key);
      if (fixture.status !== "runtime_verified") {
        errors.push(`verified event has wrong status: ${fixture.event_key}`);
      }
      if (
        runtime.support_status !== "verified" ||
        runtime.execution_status !== "observed" ||
        runtime.cursor_version !== "3.11.25"
      ) {
        errors.push(`verified runtime metadata mismatch: ${fixture.event_key}`);
      }
      if (
        runtime.evidence_reference !== ".cursor/quality-spike/events.jsonl" ||
        runtime.evidence_sha256 !== spikeHash
      ) {
        errors.push(`verified evidence reference mismatch: ${fixture.event_key}`);
      }
      if (
        !observed ||
        runtime.observation_count !== observed.count ||
        JSON.stringify(canonicalize(runtime.verified_fields)) !==
          JSON.stringify(canonicalize(observed.verified_fields))
      ) {
        errors.push(`verified payload shape mismatch: ${fixture.event_key}`);
      }
    } else if (UNOBSERVED_EVENTS.has(fixture.event_key)) {
      if (
        fixture.status !== "declared_not_runtime_verified" ||
        runtime.support_status !== "unsupported" ||
        runtime.execution_status !== "not_run" ||
        runtime.observation_count !== 0 ||
        Object.keys(runtime.verified_fields ?? {}).length !== 0
      ) {
        errors.push(`unobserved event claims runtime evidence: ${fixture.event_key}`);
      }
    } else {
      errors.push(`event is outside approved matrix: ${fixture.event_key}`);
    }
    if (fixture.event_key === "preToolUse" || fixture.event_key === "postToolUse") {
      if (
        fixture.stable_instance_id_status !== "verified" ||
        fixture.stable_instance_id_field !== "tool_use_id"
      ) {
        errors.push(`tool stable ID mismatch: ${fixture.event_key}`);
      }
    } else if (
      fixture.stable_instance_id_status === "verified" ||
      fixture.stable_instance_id_field !== null
    ) {
      errors.push(`unsupported stable ID claimed: ${fixture.event_key}`);
    }
  }
  const configuredKeys = Object.keys(hooks.hooks ?? {}).sort();
  const fixtureKeys = [...fixtureByEvent.keys()].sort();
  for (const key of configuredKeys) {
    const fixture = fixtureByEvent.get(key);
    if (!fixture) {
      errors.push(`missing capability fixture: ${key}`);
      continue;
    }
    if (
      JSON.stringify(canonicalize(fixture.configured_handlers)) !==
      JSON.stringify(canonicalize(hooks.hooks[key]))
    ) {
      errors.push(`configured_handlers mismatch: ${key}`);
    }
  }
  for (const key of fixtureKeys) {
    const fixture = fixtureByEvent.get(key);
    const configured = configuredKeys.includes(key);
    if (fixture.configured !== configured) {
      errors.push(`configured flag mismatch: ${key}`);
    }
    if (!configured && (fixture.configured_handlers?.length ?? 0) !== 0) {
      errors.push(`unconfigured event has handlers: ${key}`);
    }
  }
  if (
    configuredKeys.some((key) =>
      (hooks.hooks[key] ?? []).some((handler) =>
        handler.command.includes("capture-capability.mjs"),
      ),
    )
  ) {
    errors.push("temporary capture handler remains configured");
  }
  try {
    await fs.access(path.join(root, ".cursor", "hooks", "capture-capability.mjs"));
    errors.push("temporary capture script still exists");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  const matrix = fixtureKeys.map((key) => {
    const fixture = fixtureByEvent.get(key);
    const preventiveEligible =
      fixture.configured === true &&
      fixture.status === "runtime_verified" &&
      fixture.capability_class === "preventive" &&
      VERIFIED_PREVENTIVE_EVENTS.has(key);
    return {
      capability_class: fixture.capability_class,
      configured: fixture.configured,
      event_key: key,
      failure_behavior: fixture.failure_behavior,
      handler_count: fixture.configured_handlers?.length ?? 0,
      preventive_rollout_eligible: preventiveEligible,
      stable_instance_id_field: fixture.stable_instance_id_field,
      stable_instance_id_status: fixture.stable_instance_id_status,
      status: fixture.status,
    };
  });
  return {
    schema_version: "1.0.0",
    validator: "validate-capabilities",
    status: errors.length === 0 ? "pass" : "fail",
    at_gov_001: errors.length === 0 ? "pass" : "fail",
    errors: errors.sort(),
    evidence: {
      cursor_version: "3.11.25",
      reference: ".cursor/quality-spike/events.jsonl",
      sha256: spikeHash,
    },
    matrix,
  };
}

async function main() {
  const root = process.argv[2] ? path.resolve(process.argv[2]) : process.cwd();
  const result = await validateCapabilities(root);
  process.stdout.write(canonicalJson(result));
  if (result.status !== "pass") process.exitCode = 1;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  await main();
}

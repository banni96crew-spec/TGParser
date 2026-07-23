#!/usr/bin/env node
/** Console/network gate helper for pilot — expects console.json and network.json under qa/runs. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runs = path.join(root, "qa", "runs");
if (!fs.existsSync(runs)) {
  console.log("check-console-network: no runs yet — PASS (N/A)");
  process.exit(0);
}

let failed = 0;
for (const name of fs.readdirSync(runs)) {
  const dir = path.join(runs, name);
  if (!fs.statSync(dir).isDirectory()) continue;
  for (const file of ["console.json", "network.json"]) {
    const p = path.join(dir, file);
    if (!fs.existsSync(p)) continue;
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    const errors = Array.isArray(data.errors) ? data.errors : [];
    if (errors.length > 0) {
      console.error(`FAIL ${name}/${file}: ${errors.length} error(s)`);
      failed += errors.length;
    }
  }
}
if (failed) process.exit(1);
console.log("check-console-network: PASS");

#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runs = path.join(root, "qa", "runs");
const lines = ["# QA summary", ""];
if (fs.existsSync(runs)) {
  for (const name of fs.readdirSync(runs)) {
    lines.push(`- ${name}`);
  }
} else {
  lines.push("- (no runs)");
}
const out = path.join(root, "qa", "acceptance.md");
const existing = fs.existsSync(out) ? fs.readFileSync(out, "utf8") : "";
fs.writeFileSync(
  path.join(root, "qa", "runs-index.md"),
  lines.join("\n") + "\n",
);
console.log("summarize-qa: wrote qa/runs-index.md");
if (!existing.includes("Gate G5")) {
  console.log("summarize-qa: acceptance.md managed separately");
}

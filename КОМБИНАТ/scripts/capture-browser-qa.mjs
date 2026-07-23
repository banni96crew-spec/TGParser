#!/usr/bin/env node
/** Placeholder browser capture — records a run manifest for pilot evidence. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const runDir = path.join(root, "qa", "runs", `${stamp}-local`);
fs.mkdirSync(path.join(runDir, "screenshots"), { recursive: true });
const manifest = {
  commit: "local",
  environment: "pilot",
  browser: "manual-or-playwright",
  routes: ["/"],
  viewports: ["320", "375", "768", "1440"],
  locale: "en",
  reducedMotion: false,
  timestamp: new Date().toISOString(),
  note: "Full screenshot automation wires in when Playwright is approved as a dependency.",
};
fs.writeFileSync(path.join(runDir, "manifest.json"), JSON.stringify(manifest, null, 2));
fs.writeFileSync(
  path.join(runDir, "summary.md"),
  `# QA run ${stamp}\n\nManifest written. Attach screenshots under screenshots/.\n`,
);
console.log(`capture-browser-qa: wrote ${runDir}`);

#!/usr/bin/env node
/** Lighthouse runner stub — documents production-only policy; real CLI optional. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.join(root, "qa", "runs", "lighthouse-stub");
fs.mkdirSync(out, { recursive: true });
const report = {
  policy: "Run against next start (production), median of 3",
  budgets: {
    performance: 90,
    accessibility: 95,
    bestPractices: 95,
    seo: 95,
    lcpMs: 2500,
    cls: 0.1,
    tbtMs: 200,
  },
  status: "stub-recorded",
  note: "Install lighthouse CLI in a later dependency approval if CI should enforce numerically.",
};
fs.writeFileSync(path.join(out, "mobile.json"), JSON.stringify(report, null, 2));
console.log("run-lighthouse: stub evidence written (production policy documented)");

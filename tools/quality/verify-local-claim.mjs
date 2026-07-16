#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";

import { canonicalJson } from "./lib/quality-contract.mjs";
import { verifyLocalClaimFile } from "./lib/evidence-checkpoint.mjs";

/**
 * Independent local verifier for AT-GOV-007.
 * Never trusts claim JSON alone — recomputes file hashes from disk.
 */
async function main() {
  const claimPath = process.argv[2];
  if (!claimPath) {
    process.stderr.write(
      "usage: node tools/quality/verify-local-claim.mjs <claim.json>\n",
    );
    process.exitCode = 2;
    return;
  }
  const root = process.env.CURSOR_PROJECT_DIR ?? process.cwd();
  const result = await verifyLocalClaimFile(claimPath, { root });
  process.stdout.write(
    canonicalJson({
      schema_version: "1.0.0",
      verifier: "verify-local-claim",
      at_gov_007: result.verdict === "fail" ? "fail" : "pass_untrusted",
      trusted: false,
      verdict: result.verdict,
      errors: result.errors,
      claim_id: result.claim?.claim_id ?? null,
      claim_path: path.relative(root, path.resolve(root, claimPath)).replaceAll(
        "\\",
        "/",
      ),
    }),
  );
  if (result.verdict === "fail") process.exitCode = 1;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? "")) {
  await main();
}

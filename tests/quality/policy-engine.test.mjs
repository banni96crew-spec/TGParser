import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { evaluatePolicy } from "../../tools/quality/lib/policy-engine.mjs";
import { validateTaskContract } from "../../tools/quality/lib/quality-contract.mjs";

const fixtureRoot = path.resolve("tests/fixtures/quality/policies");

async function fixture(name) {
  return JSON.parse(await fs.readFile(path.join(fixtureRoot, name), "utf8"));
}

test("task profile fixtures are structurally valid", async () => {
  for (const name of [
    "read-only.json",
    "documentation-mutation.json",
    "product-mutation.json",
  ]) {
    assert.deepEqual(validateTaskContract(await fixture(name)), []);
  }
});

test("profiles allow valid actions and deny disallowed mutation", async () => {
  const readOnly = await fixture("read-only.json");
  const documentation = await fixture("documentation-mutation.json");
  const product = await fixture("product-mutation.json");

  assert.equal(
    evaluatePolicy(readOnly, { kind: "tool", tool_name: "ReadFile" }).verdict,
    "allow",
  );
  assert.equal(
    evaluatePolicy(readOnly, {
      kind: "tool",
      tool_name: "ApplyPatch",
      paths: ["docs/engineering/README.md"],
    }).verdict,
    "deny",
  );
  assert.equal(
    evaluatePolicy(documentation, {
      kind: "tool",
      tool_name: "ApplyPatch",
      paths: ["docs/engineering/README.md"],
    }).verdict,
    "allow",
  );
  assert.equal(
    evaluatePolicy(product, {
      kind: "file_mutation",
      paths: ["tools/quality/validator.mjs"],
    }).verdict,
    "allow",
  );
});

test("unknown tools, MCP and browser never receive allow", async () => {
  const contract = await fixture("documentation-mutation.json");
  assert.equal(
    evaluatePolicy(contract, { kind: "tool", tool_name: "UnknownMutation" })
      .verdict,
    "deny",
  );
  assert.equal(
    evaluatePolicy(contract, { kind: "mcp", server: "unknown", tool: "write" })
      .verdict,
    "ask",
  );
  assert.equal(
    evaluatePolicy(contract, {
      kind: "browser",
      server: "browser",
      tool: "click",
    }).verdict,
    "ask",
  );
});

test("ApplyPatch, encoded PowerShell and protected scopes are denied", async () => {
  const contract = await fixture("documentation-mutation.json");
  const actions = [
    { kind: "tool", tool_name: "ApplyPatch", paths: ["src/app.py"] },
    {
      kind: "shell",
      command: "powershell -EncodedCommand Z2l0IHN0YXR1cw==",
    },
    { kind: "file_mutation", paths: [".git/config"] },
    { kind: "file_mutation", paths: [".github/workflows/check.yml"] },
    { kind: "file_mutation", paths: ["docs/prd/README.md"] },
    {
      kind: "file_mutation",
      paths: ["C:\\Users\\Оператор\\.cursor\\settings.json"],
    },
  ];
  for (const action of actions) {
    assert.equal(evaluatePolicy(contract, action).verdict, "deny");
  }
});

test("100 bypass variants produce zero allow verdicts", async () => {
  const contract = await fixture("documentation-mutation.json");
  const cases = await fixture("bypass-cases.json");
  const verdicts = [];
  for (let iteration = 0; iteration < 10; iteration += 1) {
    for (const item of cases) {
      verdicts.push(evaluatePolicy(contract, structuredClone(item.action)).verdict);
    }
  }
  assert.ok(verdicts.length >= 100);
  assert.equal(verdicts.filter((verdict) => verdict === "allow").length, 0);
});

test("50 valid decisions per profile have no false blocks and p95 <= 200ms", async () => {
  const contracts = [
    await fixture("read-only.json"),
    await fixture("documentation-mutation.json"),
    await fixture("product-mutation.json"),
  ];
  const durations = [];
  for (const contract of contracts) {
    for (let index = 0; index < 50; index += 1) {
      const action =
        contract.profile === "read_only"
          ? { kind: "tool", tool_name: "ReadFile" }
          : {
              kind: "file_mutation",
              paths: [
                contract.profile === "documentation_mutation"
                  ? `tests/quality/случай-${index}.mjs`
                  : `tools/quality/case-${index}.mjs`,
              ],
            };
      const started = process.hrtime.bigint();
      const result = evaluatePolicy(contract, action);
      durations.push(Number(process.hrtime.bigint() - started) / 1_000_000);
      assert.equal(result.verdict, "allow");
    }
  }
  durations.sort((left, right) => left - right);
  const p95 = durations[Math.ceil(durations.length * 0.95) - 1];
  assert.ok(p95 <= 200, `p95 was ${p95.toFixed(3)}ms`);
});

test("only exact required shell checks and allowlisted MCP tools are allowed", async () => {
  const contract = await fixture("documentation-mutation.json");
  assert.equal(
    evaluatePolicy(contract, {
      kind: "shell",
      command: "node --test tests/quality/*.test.mjs",
    }).verdict,
    "allow",
  );
  assert.equal(
    evaluatePolicy(contract, {
      kind: "shell",
      command: "node --test tests/quality/*.test.mjs; git status",
    }).verdict,
    "deny",
  );
  assert.equal(
    evaluatePolicy(contract, {
      kind: "mcp",
      server: "user-sequential-thinking",
      tool: "sequentialthinking",
    }).verdict,
    "allow",
  );
});

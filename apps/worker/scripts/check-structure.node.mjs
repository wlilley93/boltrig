import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  LIMITS,
  StructureError,
  candidateConfig,
  checkRepository,
  loadConfig,
  parseJsonStrict,
  scanTree,
} from "./check-structure.mjs";

const METADATA = Object.freeze({
  owner: "worker-test-maintainers",
  reason: "Focused fixture for the Worker structural ratchet contract.",
  expires: "2099-12-31",
});
const CHECKER = fileURLToPath(new URL("./check-structure.mjs", import.meta.url));

function fixtureRepo(source, name = "fixture.ts") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "boltrig-worker-structure-"));
  const sourceRoot = path.join(root, "apps/worker/src");
  fs.mkdirSync(sourceRoot, { recursive: true });
  const sourcePath = path.join(sourceRoot, name);
  fs.writeFileSync(sourcePath, source, "utf8");
  return { root, sourcePath, configPath: path.join(root, "debt.json") };
}

function writeConfig(configPath, document) {
  fs.writeFileSync(configPath, `${JSON.stringify(document, null, 2)}\n`, "utf8");
}

function candidateFor(root) {
  return candidateConfig(scanTree(root, 1), METADATA);
}

function commitFixture(root, message) {
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync(
    "git",
    ["-c", "user.name=Worker Structure Tests", "-c", "user.email=worker-structure@example.invalid", "commit", "-m", message],
    { cwd: root, stdio: "ignore" },
  );
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
}

function oversizedSource() {
  const longBody = Array.from({ length: 79 }, (_, index) => `  const value${index} = ${index};`).join("\n");
  const decisions = Array.from({ length: 16 }, (_, index) => `  if (value === ${index}) return ${index};`).join("\n");
  return [
    `export function longFunction() {\n${longBody}\n}`,
    "export function manyParameters(a: number, b: number, c: number, d: number, e: number, f: number) { return a + b + c + d + e + f; }",
    `export function complex(value: number) {\n${decisions}\n  return -1;\n}`,
    "export function nested(a: boolean, b: boolean, c: boolean, d: boolean, e: boolean) {",
    "  if (a) {",
    "    for (;;) {",
    "      while (b) {",
    "        if (c) {",
    "          if (d && e) return true;",
    "        }",
    "      }",
    "      break;",
    "    }",
    "  }",
    "  return false;",
    "}",
    "",
  ].join("\n");
}

test("the pinned TypeScript AST measures clean function structure deterministically", (context) => {
  const fixture = fixtureRepo(
    "export function choose(value: boolean) {\n  if (value) return 1;\n  return 0;\n}\n",
  );
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  writeConfig(fixture.configPath, { version: 1, limits: LIMITS, exemptions: {} });

  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    today: "2026-08-12",
    minimumFiles: 1,
  });

  assert.deepEqual(report.errors, []);
  assert.equal(report.metrics.length, 1);
  assert.deepEqual(report.metrics[0].functions, [
    {
      name: "choose",
      line: 1,
      column: 1,
      lines: 4,
      parameters: 1,
      complexity: 2,
      nesting_depth: 1,
    },
  ]);
});

test("an exact debt snapshot passes and every structural dimension is measured", (context) => {
  const fixture = fixtureRepo(oversizedSource());
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  const candidate = candidateFor(fixture.root);
  writeConfig(fixture.configPath, candidate);

  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    today: "2026-08-12",
    minimumFiles: 1,
  });
  const functions = Object.values(candidate.exemptions)[0].over_limit_functions;

  assert.deepEqual(report.errors, []);
  assert.equal(functions.some((item) => item.lines > LIMITS.max_function_lines), true);
  assert.equal(functions.some((item) => item.parameters > LIMITS.max_parameters), true);
  assert.equal(functions.some((item) => item.complexity > LIMITS.max_complexity), true);
  assert.equal(functions.some((item) => item.nesting_depth > LIMITS.max_nesting_depth), true);
});

test("growth, a new violating sibling, and stale-high improvements all fail", (context) => {
  const original = oversizedSource();
  const fixture = fixtureRepo(original);
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const check = () => checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    today: "2026-08-12",
    minimumFiles: 1,
  }).errors;

  fs.writeFileSync(fixture.sourcePath, `${original}// unratcheted growth\n`, "utf8");
  assert.equal(check().some((error) => error.startsWith("file growth:")), true);

  fs.writeFileSync(
    fixture.sourcePath,
    `${original}export function newDebt() {\n${"  if (true) return true;\n".repeat(16)}}\n`,
    "utf8",
  );
  assert.equal(check().some((error) => error.includes("new over-limit function") && error.includes("newDebt")), true);

  fs.writeFileSync(fixture.sourcePath, original.replace("  const value78 = 78;\n", ""), "utf8");
  const improvementErrors = check();
  assert.equal(improvementErrors.some((error) => error.includes("baseline is stale-high")), true);
});

test("a co-edited catalogue cannot self-approve growth over the trusted Git baseline", (context) => {
  const original = oversizedSource();
  const fixture = fixtureRepo(original);
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: fixture.root });
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const baselineRef = commitFixture(fixture.root, "trusted structural baseline");

  fs.writeFileSync(fixture.sourcePath, `${original}// attacker-approved growth\n`, "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });

  assert.equal(
    report.errors.some((error) => error.includes("trusted baseline") && error.includes("growth")),
    true,
    `co-edited catalogue self-approved growth:\n${report.errors.join("\n")}`,
  );

  const candidateAttempt = spawnSync(
    process.execPath,
    [
      CHECKER,
      "--candidate",
      "--root",
      fixture.root,
      "--config",
      fixture.configPath,
      "--baseline-ref",
      baselineRef,
      "--minimum-files",
      "1",
    ],
    { encoding: "utf8" },
  );
  assert.equal(candidateAttempt.status, 1);
  assert.match(candidateAttempt.stderr, /candidate would self-approve structural debt/u);

  const complexityGrowth = original.replace(
    "  const value0 = 0;",
    "  if (true) { const value0 = 0; }",
  );
  fs.writeFileSync(fixture.sourcePath, complexityGrowth, "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const alternate = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });
  assert.equal(
    alternate.errors.some(
      (error) => error.includes("trusted baseline function-complexity growth") && error.includes("longFunction"),
    ),
    true,
    `same-size function complexity growth was approved:\n${alternate.errors.join("\n")}`,
  );
});

test("the trusted baseline permits reductions, source relocation, and expiry renewal", (context) => {
  const original = oversizedSource();
  const fixture = fixtureRepo(original);
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: fixture.root });
  const prior = candidateFor(fixture.root);
  for (const exemption of Object.values(prior.exemptions)) exemption.expires = "2026-08-11";
  writeConfig(fixture.configPath, prior);
  const baselineRef = commitFixture(fixture.root, "trusted structural baseline");

  fs.writeFileSync(fixture.sourcePath, original.replace("  const value78 = 78;\n", ""), "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });

  assert.deepEqual(report.errors, []);
  assert.equal(report.baseline.state, "enforced");
  assert.equal(report.baseline.commit, baselineRef);

  fs.writeFileSync(fixture.sourcePath, "export const clean = true;\n", "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const clean = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });
  assert.deepEqual(clean.errors, [], "fully discharged debt may remove its exemption");
});

test("the trusted baseline rejects a new debt file and refuses missing post-rollout provenance", (context) => {
  const fixture = fixtureRepo(oversizedSource());
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: fixture.root });
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const baselineRef = commitFixture(fixture.root, "trusted structural baseline");

  fs.writeFileSync(path.join(fixture.root, "apps/worker/src/new-debt.ts"), oversizedSource(), "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const newDebt = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });
  assert.equal(newDebt.errors.some((error) => error.includes("trusted baseline new debt file")), true);

  const broken = fixtureRepo(oversizedSource());
  context.after(() => fs.rmSync(broken.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: broken.root });
  const checker = path.join(broken.root, "apps/worker/scripts/check-structure.mjs");
  fs.mkdirSync(path.dirname(checker), { recursive: true });
  fs.writeFileSync(checker, "// gate exists\n", "utf8");
  const brokenBaseline = commitFixture(broken.root, "gate without provenance catalogue");
  writeConfig(broken.configPath, candidateFor(broken.root));
  const missing = checkRepository({
    repoRoot: broken.root,
    configPath: broken.configPath,
    baselineRef: brokenBaseline,
    today: "2026-08-12",
    minimumFiles: 1,
  });
  assert.equal(missing.errors.some((error) => error.includes("contains the Worker structure gate but no")), true);
});

test("only a pre-gate Git base may bootstrap the first debt census", (context) => {
  const fixture = fixtureRepo(oversizedSource());
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: fixture.root });
  const baselineRef = commitFixture(fixture.root, "source before the structure gate");
  writeConfig(fixture.configPath, candidateFor(fixture.root));

  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });

  assert.deepEqual(report.errors, []);
  assert.equal(report.baseline.state, "bootstrap");

  const unavailable = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef: "f".repeat(40),
    today: "2026-08-12",
    minimumFiles: 1,
  });
  assert.equal(unavailable.errors.some((error) => error.includes("cannot resolve trusted baseline ref")), true);
});

test("the first catalogue commit anchors later changes in the same bootstrap branch", (context) => {
  const original = oversizedSource();
  const fixture = fixtureRepo(original);
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  execFileSync("git", ["init", "--quiet"], { cwd: fixture.root });
  const preGateRef = commitFixture(fixture.root, "source before the structure gate");

  writeConfig(fixture.configPath, candidateFor(fixture.root));
  const firstCatalogueRef = commitFixture(fixture.root, "first structural census");
  fs.writeFileSync(fixture.sourcePath, `${original}// later self-approved growth\n`, "utf8");
  writeConfig(fixture.configPath, candidateFor(fixture.root));

  const report = checkRepository({
    repoRoot: fixture.root,
    configPath: fixture.configPath,
    baselineRef: preGateRef,
    today: "2026-08-12",
    minimumFiles: 1,
  });

  assert.equal(report.baseline.state, "bootstrap-anchored");
  assert.equal(report.baseline.commit, firstCatalogueRef);
  assert.equal(report.errors.some((error) => error.includes("trusted baseline") && error.includes("growth")), true);
});

test("expired, missing, clean, and raised-limit exemptions fail closed", (context) => {
  const fixture = fixtureRepo(oversizedSource());
  context.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  const exact = candidateFor(fixture.root);
  const [filePath, exemption] = Object.entries(exact.exemptions)[0];

  writeConfig(fixture.configPath, {
    ...exact,
    exemptions: { [filePath]: { ...exemption, expires: "2026-08-11" } },
  });
  assert.throws(() => loadConfig(fixture.configPath, "2026-08-12"), /expired/u);

  writeConfig(fixture.configPath, {
    ...exact,
    exemptions: { "apps/worker/src/missing.ts": exemption },
  });
  assert.equal(
    checkRepository({ repoRoot: fixture.root, configPath: fixture.configPath, minimumFiles: 1 }).errors
      .some((error) => error.includes("missing or out-of-scope")),
    true,
  );

  fs.writeFileSync(fixture.sourcePath, "export const clean = 1;\n", "utf8");
  writeConfig(fixture.configPath, exact);
  assert.equal(
    checkRepository({ repoRoot: fixture.root, configPath: fixture.configPath, minimumFiles: 1 }).errors
      .some((error) => error.includes("stale exemption for clean file")),
    true,
  );

  writeConfig(fixture.configPath, {
    ...exact,
    limits: { ...LIMITS, max_file_lines: LIMITS.max_file_lines + 1 },
  });
  assert.throws(() => loadConfig(fixture.configPath), /must remain 400/u);
});

test("malformed input, duplicate keys, parse failures, and vacuous scans are refusals", (context) => {
  assert.throws(
    () => parseJsonStrict('{"version": 1, "version": 1}'),
    (error) => error instanceof StructureError && /duplicate JSON key/u.test(error.message),
  );

  const malformed = fixtureRepo("export function broken( {\n");
  context.after(() => fs.rmSync(malformed.root, { recursive: true, force: true }));
  writeConfig(malformed.configPath, { version: 1, limits: LIMITS, exemptions: {} });
  assert.equal(
    checkRepository({ repoRoot: malformed.root, configPath: malformed.configPath, minimumFiles: 1 }).errors
      .some((error) => error.includes("cannot parse")),
    true,
  );

  const sparse = fixtureRepo("export const present = true;\n");
  context.after(() => fs.rmSync(sparse.root, { recursive: true, force: true }));
  assert.throws(() => scanTree(sparse.root, 2), /expected at least 2/u);
});

test("the repository Worker source matches its committed debt ratchets", () => {
  const report = checkRepository();
  assert.deepEqual(report.errors, [], report.errors.join("\n"));
  assert.ok(report.metrics.length >= 100);
});

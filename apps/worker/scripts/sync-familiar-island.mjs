#!/usr/bin/env node
/**
 * Carry the built Familiar island into the iOS app, or check that the copy
 * already there is the one this source tree builds.
 *
 *   node scripts/sync-familiar-island.mjs          copy dist-island/familiar-island.html
 *                                                   into ios/Boltrig/Resources/FamiliarIsland/
 *                                                   and write the manifest beside it
 *   node scripts/sync-familiar-island.mjs --check  rebuild into a scratch directory and
 *                                                   byte-compare against the committed copy
 *
 * The manifest records which source the page came from: the commit, the sha256
 * of the vendored shader, and the page's size. The check is a byte comparison
 * of the page itself, which the deterministic build makes possible; the shader
 * pin is checked as well so the manifest can never describe a shader the page
 * does not carry.
 */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WORKER = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(WORKER, "../..");
const CONFIG = "familiar-island/vite.config.ts";
const BUILT = path.join(WORKER, "dist-island", "familiar-island.html");
const FRAG = path.join(WORKER, "src/bundles/familiar/familiar.frag");
const TARGET_DIR = path.join(REPO, "ios/Boltrig/Resources/FamiliarIsland");
const TARGET = path.join(TARGET_DIR, "familiar-island.html");
const MANIFEST = path.join(TARGET_DIR, "familiar-island.manifest.json");
const STALE = "familiar island is stale: run make familiar-island";

const sha256 = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");

function sourceCommit() {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], { cwd: WORKER, encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

/** Build the page with the island config into `outDir`, through the worker's
 *  own vite so the check runs the same build the sync does. */
function build(outDir) {
  const require = createRequire(import.meta.url);
  const vite = path.join(path.dirname(require.resolve("vite/package.json")), "bin/vite.js");
  execFileSync(
    process.execPath,
    [vite, "build", "--config", CONFIG, "--outDir", outDir, "--logLevel", "warn"],
    { cwd: WORKER, stdio: "inherit" },
  );
}

function sync() {
  if (!fs.existsSync(BUILT)) {
    console.error(`sync-familiar-island: ${path.relative(WORKER, BUILT)} is missing; run pnpm run build:island first`);
    process.exit(1);
  }
  const html = fs.readFileSync(BUILT);
  fs.mkdirSync(TARGET_DIR, { recursive: true });
  fs.writeFileSync(TARGET, html);
  const manifest = {
    v: 1,
    sourceCommit: sourceCommit(),
    fragSha256: sha256(fs.readFileSync(FRAG)),
    htmlBytes: html.length,
  };
  fs.writeFileSync(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`familiar island: ${html.length} bytes -> ${path.relative(REPO, TARGET)}`);
}

function check() {
  const problems = [];
  if (!fs.existsSync(TARGET)) problems.push(`${path.relative(REPO, TARGET)} is missing`);
  if (!fs.existsSync(MANIFEST)) problems.push(`${path.relative(REPO, MANIFEST)} is missing`);
  if (problems.length === 0) {
    const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    const fragNow = sha256(fs.readFileSync(FRAG));
    if (manifest.fragSha256 !== fragNow) {
      problems.push(`manifest fragSha256 ${manifest.fragSha256} != shader ${fragNow}`);
    }
    const committed = fs.readFileSync(TARGET);
    if (manifest.htmlBytes !== committed.length) {
      problems.push(`manifest htmlBytes ${manifest.htmlBytes} != page ${committed.length}`);
    }
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "familiar-island-"));
    try {
      build(scratch);
      const rebuilt = fs.readFileSync(path.join(scratch, "familiar-island.html"));
      if (!rebuilt.equals(committed)) {
        problems.push(`rebuilt page (${rebuilt.length} bytes) differs from the committed page (${committed.length} bytes)`);
      }
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  }
  if (problems.length) {
    for (const problem of problems) console.error(`sync-familiar-island: ${problem}`);
    console.error(STALE);
    process.exit(1);
  }
  console.log("familiar island: committed page matches the source tree");
}

if (process.argv.includes("--check")) check();
else sync();

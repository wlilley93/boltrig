#!/usr/bin/env node

import { execFileSync, spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  readlink,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { homedir } from "node:os";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { SOURCE_SCOPE, sourceTreeDigest } from "./sourceDigest.mjs";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "../../../..");
const workerRoot = join(repoRoot, "apps/worker");
const statesPath = join(dirname(scriptPath), "states.json");
const manifest = JSON.parse(await readFile(statesPath, "utf8"));

const options = parseArguments(process.argv.slice(2));
if (options.help) {
  process.stdout.write(helpText());
  process.exit(0);
}
if (options.mode !== "smoke" && options.reuseServer) {
  throw new Error(
    "Durable evidence cannot reuse an existing server; the capture runner must start "
    + "the source-owned Vite process",
  );
}

const governedStates = manifest.governed_state_ids.map((id) => {
  const state = manifest.states.find((candidate) => candidate.id === id);
  if (!state) throw new Error(`Governed visual state ${id} is absent from states.json`);
  return state;
});
const additiveStates = manifest.additive_state_ids.map((id) => {
  const state = manifest.states.find((candidate) => candidate.id === id);
  if (!state) throw new Error(`Additive visual state ${id} is absent from states.json`);
  return state;
});
const selectedStateSet = options.mode === "additive-evidence"
  ? additiveStates
  : governedStates;
const selectedIds = options.states.length > 0
  ? new Set(options.states)
  : new Set(selectedStateSet.map((state) => state.id));
const selectedStateIds = selectedStateSet.map((state) => state.id);
const unknownIds = [...selectedIds].filter((id) => !selectedStateIds.includes(id));
if (unknownIds.length > 0) {
  throw new Error(
    `State(s) unavailable in ${options.mode} mode: ${unknownIds.join(", ")}`,
  );
}
if (options.mode === "evidence" && selectedIds.size !== governedStates.length) {
  throw new Error("Evidence capture is all-or-nothing and requires all seven governed states");
}
if (options.mode === "additive-evidence" && selectedIds.size !== additiveStates.length) {
  throw new Error(
    "Additive evidence capture is all-or-nothing and requires every additive state",
  );
}
const states = selectedStateSet.filter((state) => selectedIds.has(state.id));
const origin = new URL(options.origin ?? manifest.base_url);
assertCaptureOrigin(origin);

const finalRoot = options.mode === "evidence"
  ? resolve(repoRoot, manifest.current_capture_root)
  : options.mode === "additive-evidence"
    ? resolve(repoRoot, manifest.additive_capture_root)
    : resolve(repoRoot, options.outputDir ?? "work/visual-capture-smoke");
assertSafeOutputRoot(finalRoot);
await mkdir(dirname(finalRoot), { recursive: true });
const stagingRoot = await mkdtemp(join(dirname(finalRoot), `.${basename(finalRoot)}.staging-`));
await mkdir(join(stagingRoot, "shipped"), { recursive: true });

const sourceScope = SOURCE_SCOPE;
const sourceDigestBefore = await treeDigest(sourceScope);
let server = null;
let browser = null;

try {
  if (!options.reuseServer) {
    await assertOriginUnused(origin);
    server = await startVite(origin);
  } else {
    await waitForFixture(origin, options.timeoutMs);
  }

  const playwright = await loadPlaywright(options.playwrightModule);
  const browserExecutable = await resolveBrowserExecutable(
    playwright,
    options.browserExecutable,
  );
  browser = await playwright.chromium.launch({
    headless: true,
    executablePath: browserExecutable,
    args: [
      "--force-color-profile=srgb",
      "--hide-scrollbars=false",
    ],
  });

  const captures = [];
  for (const state of states) {
    process.stderr.write(`[visual-capture] waiting for ${state.id}\n`);
    captures.push(await captureState(browser, state, origin, stagingRoot, options.timeoutMs));
    process.stderr.write(`[visual-capture] captured ${state.id}\n`);
  }

  const sourceDigestAfter = await treeDigest(sourceScope);
  if (sourceDigestAfter !== sourceDigestBefore) {
    throw new Error(
      `Source changed during capture (${sourceDigestBefore} -> ${sourceDigestAfter}); `
      + "no evidence was promoted",
    );
  }

  const capturedAt = new Date().toISOString();
  const receipt = {
    schema: options.mode === "additive-evidence"
      ? "boltrig-console-additive-current-capture-manifest.v1"
      : "boltrig-console-current-capture-manifest.v1",
    ...(options.mode === "additive-evidence" ? { captureSet: "additive" } : {}),
    status: "captured_unreviewed",
    visualVerdict: "not_assessed",
    vdsReviewsUpdated: false,
    capturedAt,
    viewport: {
      width: manifest.viewport.width,
      height: manifest.viewport.height,
      deviceScaleFactor: 1,
    },
    sourceBinding: {
      status: "current_at_capture",
      scope: sourceScope,
      digestAlgorithm: "sha256-path-type-content-v1",
      digestBeforeCapture: sourceDigestBefore,
      digestAfterCapture: sourceDigestAfter,
      sourceUnchangedDuringCapture: true,
      ...gitIdentity(),
    },
    runner: {
      script: relative(repoRoot, scriptPath),
      node: process.version,
      browser: browser.browserType().name(),
      browserVersion: browser.version(),
      browserExecutable,
      origin: origin.origin,
      readiness: "two stable animation frames after fonts, requests, route and DOM contract settle",
    },
    states: captures,
    reviewPolicy: {
      pixelsClaimed: false,
      instruction: "Regenerate comparisons and complete authority review before changing a VDS verdict.",
    },
  };
  await writeFile(
    join(stagingRoot, "capture-manifest.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
    "utf8",
  );
  await writeFile(
    join(stagingRoot, "shipped.sha256"),
    `${captures.map((capture) => `${capture.sha256}  shipped/${capture.state}.png`).join("\n")}\n`,
    "utf8",
  );

  // Close the renderer before the final source check so no late browser work
  // can be mistaken for a completed capture.
  await browser.close();
  browser = null;
  const finalSourceDigest = await treeDigest(sourceScope);
  if (finalSourceDigest !== sourceDigestBefore) {
    throw new Error(
      `Source changed before evidence promotion (${sourceDigestBefore} -> ${finalSourceDigest}); `
      + "no evidence was promoted",
    );
  }

  await replaceDirectory(stagingRoot, finalRoot);
  process.stdout.write(`${JSON.stringify({
    status: receipt.status,
    mode: options.mode,
    outputRoot: relative(repoRoot, finalRoot),
    sourceDigest: sourceDigestBefore,
    states: captures.map(({ state, sha256, width, height }) => ({ state, sha256, width, height })),
  }, null, 2)}\n`);
} catch (error) {
  await rm(stagingRoot, { recursive: true, force: true });
  throw error;
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await stopServer(server);
}

function parseArguments(args) {
  const parsed = {
    help: false,
    mode: "smoke",
    origin: null,
    outputDir: null,
    playwrightModule: null,
    browserExecutable: null,
    reuseServer: false,
    states: [],
    timeoutMs: 30_000,
  };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--help" || argument === "-h") parsed.help = true;
    else if (argument === "--reuse-server") parsed.reuseServer = true;
    else if (argument === "--additive-evidence") parsed.mode = "additive-evidence";
    else if (argument === "--evidence") parsed.mode = "evidence";
    else if (argument === "--smoke") parsed.mode = "smoke";
    else if (argument === "--state") parsed.states.push(requiredValue(args, ++index, argument));
    else if (argument.startsWith("--state=")) parsed.states.push(argument.slice("--state=".length));
    else if (argument === "--origin") parsed.origin = requiredValue(args, ++index, argument);
    else if (argument.startsWith("--origin=")) parsed.origin = argument.slice("--origin=".length);
    else if (argument === "--output-dir") parsed.outputDir = requiredValue(args, ++index, argument);
    else if (argument.startsWith("--output-dir=")) parsed.outputDir = argument.slice("--output-dir=".length);
    else if (argument === "--playwright") parsed.playwrightModule = requiredValue(args, ++index, argument);
    else if (argument.startsWith("--playwright=")) parsed.playwrightModule = argument.slice("--playwright=".length);
    else if (argument === "--browser-executable") parsed.browserExecutable = requiredValue(args, ++index, argument);
    else if (argument.startsWith("--browser-executable=")) parsed.browserExecutable = argument.slice("--browser-executable=".length);
    else if (argument === "--timeout-ms") parsed.timeoutMs = parseTimeout(requiredValue(args, ++index, argument));
    else if (argument.startsWith("--timeout-ms=")) parsed.timeoutMs = parseTimeout(argument.slice("--timeout-ms=".length));
    else throw new Error(`Unknown argument: ${argument}`);
  }
  if (parsed.mode !== "smoke" && parsed.outputDir) {
    throw new Error(
      "--output-dir is smoke-only; evidence modes use their manifest-declared durable roots",
    );
  }
  return parsed;
}

function requiredValue(args, index, flag) {
  const value = args[index];
  if (!value || value.startsWith("--")) throw new Error(`${flag} requires a value`);
  return value;
}

function parseTimeout(value) {
  const timeout = Number.parseInt(value, 10);
  if (!Number.isFinite(timeout) || timeout < 1_000 || timeout > 300_000) {
    throw new Error("--timeout-ms must be between 1000 and 300000");
  }
  return timeout;
}

function helpText() {
  return `Capture the governed Worker visual states through their fail-closed DOM contract.\n\n`
    + `Usage:\n`
    + `  node apps/worker/tests/visual/capture-current.mjs --smoke [--state ID] [--output-dir PATH]\n`
    + `  node apps/worker/tests/visual/capture-current.mjs --evidence\n\n`
    + `  node apps/worker/tests/visual/capture-current.mjs --additive-evidence\n\n`
    + `Options:\n`
    + `  --evidence       Capture all seven states into the declared durable current/ evidence root.\n`
    + `  --additive-evidence  Capture every additive state into its separate source-bound current/ root.\n`
    + `  --smoke          Capture into work/visual-capture-smoke (default).\n`
    + `  --reuse-server   Use an already-running Vite server for smoke capture only.\n`
    + `  --origin URL     Override the manifest origin only; paths and queries remain declared.\n`
    + `  --playwright P   Explicit Playwright module directory or index.mjs path.\n`
    + `  --browser-executable P  Explicit Chromium/Chrome executable.\n`
    + `  --timeout-ms N   Per-state readiness timeout (default 30000).\n`;
}

function assertCaptureOrigin(origin) {
  if (!/^https?:$/.test(origin.protocol) || origin.pathname !== "/" || origin.search || origin.hash) {
    throw new Error(`Capture origin must be a bare HTTP(S) origin, received ${origin.href}`);
  }
  if (!origin.port) throw new Error("Capture origin must declare an explicit port");
}

function assertSafeOutputRoot(outputRoot) {
  const relativePath = relative(repoRoot, outputRoot);
  if (!relativePath || relativePath === "." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`Capture output must be a scoped directory inside ${repoRoot}`);
  }
  if (relativePath.split(sep).length < 2) {
    throw new Error(`Capture output is too broad: ${relativePath}`);
  }
}

async function assertOriginUnused(origin) {
  try {
    const response = await fetch(new URL("/tests/visual/parity.html", origin), {
      signal: AbortSignal.timeout(500),
    });
    if (response) {
      throw new Error(`${origin.origin} is already serving HTTP; pass --reuse-server explicitly`);
    }
  } catch (error) {
    if (String(error).includes("already serving HTTP")) throw error;
  }
}

async function startVite(origin) {
  const child = spawn(
    process.execPath,
    [
      join(workerRoot, "node_modules/vite/bin/vite.js"),
      "--host", origin.hostname,
      "--port", origin.port,
      "--strictPort",
    ],
    { cwd: workerRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  child.stdout.on("data", (chunk) => { output += chunk.toString(); });
  child.stderr.on("data", (chunk) => { output += chunk.toString(); });
  child.on("error", (error) => { output += `\n${error.stack ?? error}`; });
  try {
    await waitForFixture(origin, options.timeoutMs, child);
    return { child, output: () => output };
  } catch (error) {
    child.kill("SIGTERM");
    throw new Error(`${error.message}\nVite output:\n${output}`);
  }
}

async function waitForFixture(origin, timeoutMs, child = null) {
  const deadline = Date.now() + timeoutMs;
  const url = new URL("/tests/visual/parity.html", origin);
  while (Date.now() < deadline) {
    if (child && child.exitCode !== null) throw new Error(`Vite exited with code ${child.exitCode}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
      if (response.ok && (await response.text()).includes("Boltrig visual parity fixture")) return;
    } catch {
      // Server startup is expected to refuse connections for a short interval.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw new Error(`Timed out waiting for ${url.href}`);
}

async function stopServer(server) {
  if (server.child.exitCode !== null) return;
  server.child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolvePromise) => server.child.once("exit", resolvePromise)),
    new Promise((resolvePromise) => setTimeout(resolvePromise, 2_000)),
  ]);
  if (server.child.exitCode === null) server.child.kill("SIGKILL");
}

async function loadPlaywright(explicitModule) {
  const fallback = join(
    homedir(),
    ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs",
  );
  const candidates = [
    explicitModule,
    process.env.BOLTRIG_PLAYWRIGHT_MODULE,
    "playwright",
    fallback,
  ].filter(Boolean);
  const failures = [];
  for (const candidate of candidates) {
    try {
      const specifier = candidate === "playwright"
        ? candidate
        : pathToFileURL(await resolvePlaywrightEntry(candidate)).href;
      const loaded = await import(specifier);
      if (!loaded.chromium) throw new Error("module does not export chromium");
      return loaded;
    } catch (error) {
      failures.push(`${candidate}: ${error.message}`);
    }
  }
  throw new Error(
    "Playwright is unavailable. Pass --playwright /absolute/path/to/playwright/index.mjs.\n"
    + failures.join("\n"),
  );
}

async function resolvePlaywrightEntry(candidate) {
  const absolute = resolve(candidate);
  const metadata = await lstat(absolute);
  return metadata.isDirectory() ? join(absolute, "index.mjs") : absolute;
}

async function resolveBrowserExecutable(playwright, explicitExecutable) {
  const requested = explicitExecutable ?? process.env.BOLTRIG_BROWSER_EXECUTABLE;
  if (requested) {
    const absolute = resolve(requested);
    await access(absolute);
    return absolute;
  }

  const playwrightDefault = playwright.chromium.executablePath();
  try {
    await access(playwrightDefault);
    return playwrightDefault;
  } catch {
    // Bundled Playwright can outlive its headless-shell download. Prefer a
    // matching full Chromium-for-Testing build already present in its cache.
  }

  const cacheRoot = process.platform === "darwin"
    ? join(homedir(), "Library/Caches/ms-playwright")
    : join(homedir(), ".cache/ms-playwright");
  let entries = [];
  try {
    entries = await readdir(cacheRoot, { withFileTypes: true });
  } catch {
    entries = [];
  }
  const revisions = entries
    .filter((entry) => entry.isDirectory() && /^chromium-\d+$/.test(entry.name))
    .map((entry) => entry.name)
    .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
  for (const revision of revisions) {
    const candidates = process.platform === "darwin"
      ? [
          join(cacheRoot, revision, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
          join(cacheRoot, revision, "chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        ]
      : process.platform === "win32"
        ? [join(cacheRoot, revision, "chrome-win64/chrome.exe")]
        : [join(cacheRoot, revision, "chrome-linux64/chrome")];
    for (const candidate of candidates) {
      try {
        await access(candidate);
        return candidate;
      } catch {
        // Try the next installed revision.
      }
    }
  }
  throw new Error(
    `Playwright's browser is missing at ${playwrightDefault}. `
    + "Pass --browser-executable /absolute/path/to/Chromium.",
  );
}

async function captureState(browserInstance, state, captureOrigin, stageRoot, timeoutMs) {
  const context = await browserInstance.newContext({
    viewport: { width: manifest.viewport.width, height: manifest.viewport.height },
    screen: { width: manifest.viewport.width, height: manifest.viewport.height },
    deviceScaleFactor: 1,
    colorScheme: "dark",
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "Europe/London",
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error"
      && !message.text().startsWith("Failed to load resource:")
    ) pageErrors.push(`console: ${message.text()}`);
  });

  try {
    const url = new URL(state.url);
    url.protocol = captureOrigin.protocol;
    url.hostname = captureOrigin.hostname;
    url.port = captureOrigin.port;
    await page.goto(url.href, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    try {
      await page.waitForFunction(
        ({ id, width, height }) => {
          const contract = window.__boltrigVisualCaptureContract;
          return document.documentElement.dataset.visualReady === id
            && contract?.ready === true
            && contract.state === id
            && contract.stableFrames >= 2
            && contract.viewport.width === width
            && contract.viewport.height === height
            && contract.viewport.devicePixelRatio === 1
            && contract.pendingRequests === 0
            && contract.missingRequestPrefixes.length === 0
            && contract.fixtureMisses.length === 0
            && contract.contractMisses.length === 0;
        },
        { id: state.id, width: manifest.viewport.width, height: manifest.viewport.height },
        { timeout: timeoutMs, polling: "raf" },
      );
    } catch (error) {
      const diagnostics = await page.evaluate(() => ({
        captureContract: window.__boltrigVisualCaptureContract ?? null,
        documentState: { ...document.documentElement.dataset },
      }));
      throw new Error(
        `${state.id} did not settle within ${timeoutMs}ms: ${error.message}\n`
        + `${JSON.stringify(diagnostics, null, 2)}\n`
        + `${pageErrors.join("\n")}`,
      );
    }
    await page.evaluate(() => new Promise((resolvePromise) => {
      requestAnimationFrame(() => requestAnimationFrame(resolvePromise));
    }));
    const before = await page.evaluate(() => window.__boltrigVisualCaptureContract);
    assertReadyContract(state, before);
    if (pageErrors.length > 0) {
      throw new Error(`${state.id} emitted page errors:\n${pageErrors.join("\n")}`);
    }

    const path = join(stageRoot, "shipped", `${state.id}.png`);
    await page.screenshot({
      path,
      type: "png",
      fullPage: false,
      caret: "hide",
      scale: "css",
    });
    const after = await page.evaluate(() => window.__boltrigVisualCaptureContract);
    assertReadyContract(state, after);
    const bytes = await readFile(path);
    const { width, height } = pngDimensions(bytes);
    if (width !== manifest.viewport.width || height !== manifest.viewport.height) {
      throw new Error(`${state.id} screenshot is ${width}x${height}, expected 1440x900`);
    }
    return {
      state: state.id,
      figmaNodeId: state.figma_node_id,
      target: state.target_output,
      url: url.href,
      hash: state.hash,
      settledSelector: state.settled_selector,
      output: options.mode === "smoke"
        ? relative(repoRoot, join(finalRoot, "shipped", `${state.id}.png`))
        : state.current_output,
      sha256: sha256(bytes),
      width,
      height,
      captureContract: after,
    };
  } finally {
    await context.close();
  }
}

function assertReadyContract(state, contract) {
  if (!contract) throw new Error(`${state.id} did not publish a capture contract`);
  const problems = [];
  if (!contract.ready) problems.push("ready=false");
  if (contract.state !== state.id) problems.push(`state=${contract.state}`);
  if (contract.actualHash !== state.hash) problems.push(`hash=${contract.actualHash}`);
  if (contract.stableFrames < 2) problems.push(`stableFrames=${contract.stableFrames}`);
  if (contract.pendingRequests !== 0) problems.push(`pendingRequests=${contract.pendingRequests}`);
  if (contract.missingRequestPrefixes.length) problems.push(`missing=${contract.missingRequestPrefixes.join(",")}`);
  if (contract.fixtureMisses.length) problems.push(`fixtureMisses=${contract.fixtureMisses.join(",")}`);
  if (contract.contractMisses.length) problems.push(`contractMisses=${contract.contractMisses.join(",")}`);
  if (problems.length > 0) throw new Error(`${state.id} capture contract failed: ${problems.join("; ")}`);
}

function pngDimensions(bytes) {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (bytes.length < 24 || signature.some((value, index) => bytes[index] !== value)) {
    throw new Error("Capture is not a PNG file");
  }
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

// treeDigest and its directory walk moved to ./sourceDigest.mjs, which the test
// that CHECKS this receipt imports too. The walk counted untracked files, so a
// receipt could only ever match on the one machine that captured it.
function treeDigest(scopes) {
  return sourceTreeDigest(repoRoot, scopes);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function gitIdentity() {
  const git = (...args) => execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" }).trim();
  return {
    branch: git("branch", "--show-current"),
    head: git("rev-parse", "HEAD"),
    dirty: git("status", "--porcelain", "--", ...sourceScope).length > 0,
  };
}

async function replaceDirectory(stage, destination) {
  const backup = `${destination}.previous-${randomUUID()}`;
  let hadDestination = false;
  try {
    await access(destination);
    const metadata = await lstat(destination);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new Error(`Refusing to replace non-directory capture destination ${destination}`);
    }
    await rename(destination, backup);
    hadDestination = true;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  try {
    await rename(stage, destination);
  } catch (error) {
    if (hadDestination) await rename(backup, destination);
    throw error;
  }
  if (hadDestination) await rm(backup, { recursive: true, force: true });
}

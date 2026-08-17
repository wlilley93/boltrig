#!/usr/bin/env node

// Drive the setup flow to the companion step and report what the panel is
// actually painted, per companion and per skin.
//
// WHY MEASURED STYLE RATHER THAN A SCREENSHOT. The defect this exists to catch
// is a seam: a body that paints an opaque rectangle standing on a surface of a
// slightly different colour. Two near-blacks a few units apart are a hard thing
// to judge from a PNG and a trivial thing to compare as numbers, so the check is
// "does the panel's computed background equal the body's own edge colour",
// which is a string comparison. render-bodies.mjs supplies the other half of
// that pair; the expectations below are its measured output.
//
// A PNG is written as well, because the copy's legibility over a scrim that has
// been removed is a judgement rather than a number.
//
// PLAYWRIGHT IS NOT A DEPENDENCY OF apps/worker AND MUST NOT BECOME ONE --
// package.json there is public graph. Pass --playwright <abs path>.
//
//   node apps/worker/tests/visual/capture-onboarding.mjs \
//     --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs

import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { decodePng, seamAcross } from "./seam.mjs";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "../../../..");
const workerRoot = join(repoRoot, "apps/worker");

/**
 * What each companion should leave the panel painted, and why that value.
 *
 * `surface: null` means the panel must stay on its own token -- the body is
 * transparent, so tinting the panel would be colouring in a rectangle that is
 * not there. The hexes are the `base` column of `render-bodies.mjs` -- the
 * per-channel median of a real frame, which is the colour a body mostly is.
 * NOT its `edge`: a body ending in a vignette is darkest in its last few
 * pixels, and a host painted that value leaves the rest of the body standing
 * proud as a brighter rectangle. If a shader's background moves, that script is
 * what tells you these have gone stale.
 */
const EXPECTATIONS = [
  { name: "Familiar", skin: null, surface: null },
  { name: "Jarvis", skin: "Instrument", surface: "rgb(5, 5, 8)" },
  { name: "Jarvis", skin: "Age of Ultron", surface: null },
  { name: "Ultron", skin: null, surface: null },
  { name: "Colossus", skin: null, surface: "rgb(6, 5, 4)" },
];

/**
 * How big a step across the card's edge is allowed, in 0-255 units.
 *
 * Not zero, and it cannot be. Three of these bodies END in a gradient -- a
 * vignette, a diagonal glass sheen, a radial core glow -- so a rectangle of
 * body against a flat host has SOME step at its border by construction. What
 * matters is whether the step reads as an edge, and below about three units at
 * these near-black levels it does not. The value that produced the complaint
 * this exists to catch was 5-plus, on Colossus, at the top of the card.
 */
const SEAM_TOLERANCE = 3;

const options = parseArguments(process.argv.slice(2));
if (options.help) {
  process.stdout.write(helpText());
  process.exit(0);
}

const playwright = await loadPlaywright(options.playwrightModule);
const origin = `http://127.0.0.1:${options.port}`;
const server = options.reuseServer ? null : await startVite(options.port);
let browser = null;
const rows = [];

try {
  browser = await playwright.chromium.launch({
    headless: true,
    executablePath: resolveBrowserExecutable(options.browserExecutable),
    args: [
      "--no-sandbox",
      "--use-gl=swiftshader",
      "--enable-unsafe-swiftshader",
      "--force-color-profile=srgb",
    ],
  });
  const context = await browser.newContext({
    viewport: { width: options.width, height: options.height },
    deviceScaleFactor: 1,
    colorScheme: options.theme,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") process.stderr.write(`[page] ${message.text()}\n`);
  });
  await page.goto(`${origin}/tests/visual/onboarding-preview.html`, { waitUntil: "load" });
  // The palette is chosen by data-theme on the root, NOT by prefers-color-scheme
  // -- so a context colourScheme alone leaves this on the light palette and a
  // "dark" run would quietly measure the light one.
  await page.evaluate((theme) => {
    document.documentElement.dataset.theme = theme;
  }, options.theme);

  await enterTheCompanionStep(page);

  for (const expectation of EXPECTATIONS) {
    await page.getByRole("radio", { name: expectation.name, exact: true }).click();
    if (expectation.skin) {
      await page.getByRole("radiogroup", { name: "Appearance" })
        .getByRole("radio", { name: expectation.skin, exact: true }).click();
    }
    // The body is a rAF loop against a software rasteriser; give it frames
    // before asking what is on screen.
    await page.waitForTimeout(options.settleMs);
    const observed = await page.evaluate(() => {
      const panel = document.querySelector(".onboarding-panel");
      const card = document.querySelector(".companion-card");
      const copy = document.querySelector(".companion-copy");
      const styleOf = (node) => (node ? getComputedStyle(node) : null);
      const panelStyle = styleOf(panel);
      return {
        companion: card?.getAttribute("data-companion") ?? null,
        skin: card?.getAttribute("data-skin") ?? null,
        panelBackground: panelStyle?.backgroundColor ?? null,
        panelBackdrop: panelStyle?.backdropFilter ?? null,
        panelText: panelStyle?.color ?? null,
        cardBackground: styleOf(card)?.backgroundColor ?? null,
        copyBackgroundImage: styleOf(copy)?.backgroundImage ?? null,
        copyBackgroundColor: styleOf(copy)?.backgroundColor ?? null,
      };
    });
    const label = expectation.skin
      ? `${expectation.name}/${expectation.skin}`
      : expectation.name;
    // The seam is measured on the COMPOSITED page, not on either layer alone.
    // A body's own frame can be measured offscreen and the host's colour read
    // from computed style, but the step between them only exists once the
    // browser has stacked one on the other.
    const shot = await page.screenshot();
    const box = await page.locator(".companion-card").boundingBox();
    const seam = box ? seamAcross(decodePng(shot), box) : null;
    rows.push({
      label,
      expectation,
      observed,
      seam,
      ...verdictFor(expectation, observed, seam),
    });
    if (options.writePng) {
      const file = join(options.outDir, `${options.theme}--${label.replace(/\W+/g, "-").toLowerCase()}.png`);
      await mkdir(dirname(file), { recursive: true });
      await writeFile(file, shot);
    }
  }
} finally {
  await browser?.close();
  server?.kill("SIGTERM");
}

report(rows);
if (rows.some((row) => !row.ok)) process.exitCode = 1;

// --------------------------------------------------------------------- checks

/**
 * Two independent claims, because they fail independently.
 *
 * SURFACE is the seam: an opaque body needs the panel on its exact colour, and
 * a transparent one needs the panel left on its own token in whichever theme is
 * running -- so "not tinted" is checked as "not either of the two tints",
 * rather than against a hardcoded light/dark value that would make this script
 * theme-specific.
 *
 * SCRIM is the footer: the copy must paint nothing at all. A gradient there is
 * a background-IMAGE, so a colour-only check would pass straight over it.
 */
function verdictFor(expectation, observed, seam) {
  const tints = new Set(EXPECTATIONS.map((item) => item.surface).filter(Boolean));
  const surfaceOk = expectation.surface
    ? observed.panelBackground === expectation.surface
    : !tints.has(observed.panelBackground);
  const scrimOk = observed.copyBackgroundImage === "none"
    && isTransparent(observed.copyBackgroundColor);
  const cardOk = isTransparent(observed.cardBackground);
  const seamOk = !seam || seam.worst <= SEAM_TOLERANCE;
  return {
    ok: surfaceOk && scrimOk && cardOk && seamOk,
    surfaceOk,
    scrimOk,
    cardOk,
    seamOk,
  };
}

/** Computed colours arrive as color(srgb ...) for token-derived values. */
function shortColour(value) {
  const match = /^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/.exec(value ?? "");
  if (!match) return String(value);
  const channel = (raw) => Math.round(Number(raw) * 255);
  const alpha = match[4] === undefined ? "" : ` /${match[4]}`;
  return `rgb(${channel(match[1])},${channel(match[2])},${channel(match[3])})${alpha}`;
}

function isTransparent(value) {
  return value === "rgba(0, 0, 0, 0)" || value === "transparent";
}

// ---------------------------------------------------------------------- flow

/**
 * Step 0 is the name, and the flow will not advance without one. Typing it and
 * pressing the real primary action is the point: a preview that jumped straight
 * to step 1 by fiddling with state would not prove the step is reachable.
 */
async function enterTheCompanionStep(page) {
  const name = page.locator(".onboarding-name input");
  await name.waitFor({ state: "visible", timeout: 20000 });
  await name.fill("Preview");
  await page.getByRole("button", { name: /continue/i }).click();
  await page.locator(".companion-card").waitFor({ state: "visible", timeout: 20000 });
}

// -------------------------------------------------------------------- report

function report(results) {
  if (options.json) {
    process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);
    return;
  }
  const header = "companion            panel surface     scrim  card  seam   verdict";
  process.stdout.write(`${header}\n${"-".repeat(header.length)}\n`);
  for (const row of results) {
    process.stdout.write(
      `${row.label.padEnd(20)} ${shortColour(row.observed.panelBackground).padEnd(17)}`
      + ` ${row.scrimOk ? "ok   " : "SCRIM"}  ${row.cardOk ? "ok  " : "CARD"}`
      + `  ${String(row.seam?.worst ?? "-").padStart(4)}  `
      + `${row.ok ? "pass" : "FAIL"}\n`,
    );
    if (!row.seamOk && row.seam) {
      for (const [edge, values] of Object.entries(row.seam)) {
        if (edge === "worst" || !values || values.step <= SEAM_TOLERANCE) continue;
        process.stdout.write(
          `  ${edge}: panel ${values.outside.join(",")} vs body ${values.inside.join(",")}`
          + ` -- step ${values.step}\n`,
        );
      }
    }
    if (!row.surfaceOk) {
      process.stdout.write(
        `  expected ${row.expectation.surface ?? "no tint"}, saw ${row.observed.panelBackground}\n`,
      );
    }
    if (!row.scrimOk) {
      process.stdout.write(
        `  copy still paints: image ${row.observed.copyBackgroundImage},`
        + ` colour ${row.observed.copyBackgroundColor}\n`,
      );
    }
  }
}

// ------------------------------------------------------------------ plumbing

async function startVite(port) {
  const child = spawn(
    "./node_modules/.bin/vite",
    ["--port", String(port), "--strictPort", "--host", "127.0.0.1"],
    { cwd: workerRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  child.stderr.on("data", (data) => process.stderr.write(`[vite] ${data}`));
  await waitForOrigin(`http://127.0.0.1:${port}`, 60000);
  return child;
}

async function waitForOrigin(origin, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const response = await fetch(origin, { method: "GET" });
      if (response.ok || response.status === 404) return;
    } catch {
      // Not listening yet.
    }
    if (Date.now() > deadline) throw new Error(`${origin} never came up`);
    await new Promise((done) => setTimeout(done, 250));
  }
}

async function loadPlaywright(modulePath) {
  if (!modulePath) {
    throw new Error(
      "--playwright <abs path to playwright/index.mjs> is required. Playwright is "
      + "deliberately NOT a dependency of apps/worker; that package.json is public graph.",
    );
  }
  const absolute = isAbsolute(modulePath) ? modulePath : resolve(process.cwd(), modulePath);
  if (!existsSync(absolute)) throw new Error(`No Playwright module at ${absolute}`);
  return import(pathToFileURL(absolute).href);
}

function resolveBrowserExecutable(explicit) {
  if (explicit) return explicit;
  const cache = join(process.env.HOME ?? "", ".cache/ms-playwright");
  const found = readdirSafe(cache)
    .filter((name) => /^chromium-\d+$/.test(name))
    .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]))
    .flatMap((name) => [
      join(cache, name, "chrome-linux64/chrome"),
      join(cache, name, "chrome-linux/chrome"),
    ])
    .find((candidate) => existsSync(candidate));
  if (!found) throw new Error(`No Chromium under ${cache}. Pass --browser <abs path>.`);
  return found;
}

function readdirSafe(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

function parseArguments(argv) {
  const parsed = {
    help: false,
    json: false,
    writePng: true,
    theme: "dark",
    port: 1427,
    width: 1280,
    height: 900,
    settleMs: 900,
    reuseServer: false,
    outDir: resolve(repoRoot, "work/onboarding-preview"),
    playwrightModule: null,
    browserExecutable: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => {
      const value = argv[++i];
      if (value === undefined) throw new Error(`${arg} needs a value`);
      return value;
    };
    switch (arg) {
      case "--help": case "-h": parsed.help = true; break;
      case "--json": parsed.json = true; break;
      case "--no-png": parsed.writePng = false; break;
      case "--reuse-server": parsed.reuseServer = true; break;
      case "--theme": parsed.theme = next() === "light" ? "light" : "dark"; break;
      case "--port": parsed.port = Number(next()); break;
      case "--settle": parsed.settleMs = Number(next()); break;
      case "--size": {
        const [w, h] = next().split("x").map(Number);
        parsed.width = w;
        parsed.height = h;
        break;
      }
      case "--out": parsed.outDir = resolve(process.cwd(), next()); break;
      case "--playwright": parsed.playwrightModule = next(); break;
      case "--browser": parsed.browserExecutable = next(); break;
      default: throw new Error(`Unrecognised argument ${arg}`);
    }
  }
  return parsed;
}

function helpText() {
  return `Drive setup to the companion step and check what the panel is painted.

  node apps/worker/tests/visual/capture-onboarding.mjs --playwright <abs path> [options]

  --theme dark|light   default dark
  --size <w>x<h>       default 1280x900
  --port <n>           vite dev port, default 1427
  --reuse-server       do not start vite; assume it is already on --port
  --settle <ms>        frames to allow before reading, default 900
  --out <dir>          PNGs, default work/onboarding-preview
  --no-png             styles only
  --json               machine-readable

Exits non-zero if any companion's panel is not on the surface its body needs,
if the copy is painting a scrim again, if the card has grown a background, or if
the step across the card's edge in the composited page exceeds the seam
tolerance -- which is the defect the whole arrangement exists to remove.
`;
}

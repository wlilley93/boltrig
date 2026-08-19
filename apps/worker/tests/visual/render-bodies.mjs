#!/usr/bin/env node

// Offscreen render harness for the animated character bodies.
//
// WHY THIS EXISTS. Jarvis V2, Ultron and Colossus are GPU particle systems, and
// until this script existed the only way to see one was a full `vite build` and
// a static deploy to dev.boltrig.io. Worse, a GLSL compile error is SILENT at
// runtime -- the renderer sets status "failed" and removes its canvas, so the
// stage simply shows nothing and looks like a CSS problem. Three tuning rounds
// were spent on a centre that burned white; the number that catches that defect
// is one line of arithmetic over the middle of the frame, and it is printed
// here.
//
// WHAT IT MEASURES, and why these numbers rather than a screenshot.
//
//   sat    mean HSV saturation over the sampled region. A hologram that has
//          gone white is DESATURATED -- this is the number that moves when the
//          centre blows out, and it moves before a human notices.
//   val    mean HSV value. sat low AND val high is white; sat low and val low
//          is just empty frame, which is a different defect.
//   white  fraction of pixels with all three channels >= 0.92. The blowout
//          itself, counted rather than eyeballed.
//   ink    fraction of pixels with any channel >= 0.02, i.e. how much of the
//          region the body actually covers. Guards the opposite failure: a
//          shader that compiled, rendered nothing, and scored a beautiful sat.
//
// "Centre" is the centred box of half the width and half the height, so a
// QUARTER of the frame area -- the region the iris and the core lobes occupy.
//
// PLAYWRIGHT IS NOT A DEPENDENCY OF apps/worker AND MUST NOT BECOME ONE.
// package.json there is public graph. Pass --playwright <abs path>; the same
// convention capture-current.mjs uses.
//
// Usage:
//   node apps/worker/tests/visual/render-bodies.mjs \
//     --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs
//
//   --body jarvis-v1|jarvis-v2|ultron|colossus|familiar   repeatable; default all
//   --mode standby|listening|thinking|working|speaking   repeatable;
//                                   default standby,thinking,speaking
//   --level <0..1>                  voice level inside the mode, default 0.8
//   --frames <n>                    simulation steps before the read, default 180
//   --size <w>x<h>                  default 512x512
//   --out <dir>                     PNGs; default work/body-renders
//   --no-png                        numbers only, no files
//   --json                          machine-readable, one object
//   --tuning <json>                 override canvas/bodyTuning, in exactly the
//                                   shape shader-bench.html's Copy settings
//                                   prints, so a look judged by eye can be
//                                   measured without the bench
//   --phenotype <json>              a measured mood, e.g. '{"fatigue":1}'. The
//                                   only way to check that a scalar the bundle
//                                   claims to read actually moves anything --
//                                   seven of the ten were being dropped while
//                                   the claim stood.

import { existsSync, readdirSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { deflateSync } from "node:zlib";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "../../../..");
const workerRoot = join(repoRoot, "apps/worker");

/* jarvis-v1 is the instrument dial, jarvis-v2 the neural field: ONE character
 * wearing two skins, but two entirely separate renderers, and the pair is the
 * whole point of measuring here -- v1 paints an opaque near-black canvas and v2
 * composites with alpha, which is what decides whether the onboarding panel has
 * to take the body's colour or can let it float on the glass. */
const ALL_BODIES = ["jarvis-v1", "jarvis-v2", "ultron", "colossus", "familiar"];
// `error` is the Familiar's alone -- the other bodies have no failure preset and
// must not be asked for one, since an empty delta is a state the enum claims and
// the body does not honour. Asking for it on Jarvis renders his standby, which
// is the honest answer rather than an invented look.
const ALL_MODES = ["standby", "listening", "thinking", "working", "speaking", "error"];

let options;

async function main() {
  options = parseArguments(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(helpText());
    process.exit(0);
  }

  const bundle = await buildBundle();
  const page = pageHtml(bundle);

  const playwright = await loadPlaywright(options.playwrightModule);
  const browser = await playwright.chromium.launch({
    headless: true,
    executablePath: resolveBrowserExecutable(options.browserExecutable),
    args: [
      "--no-sandbox",
      "--use-gl=swiftshader",
      "--enable-unsafe-swiftshader",
      "--force-color-profile=srgb",
    ],
  });

  const rows = [];
  try {
    const context = await browser.newContext({
      viewport: { width: options.width, height: options.height },
      deviceScaleFactor: 1,
    });
    const tab = await context.newPage();
    tab.on("console", (message) => {
      if (message.type() === "error") process.stderr.write(`[page] ${message.text()}\n`);
    });
    await tab.setContent(page, { waitUntil: "load" });

    for (const body of options.bodies) {
      for (const mode of options.modes) {
        const result = await tab.evaluate(
          ([bodyName, modeName, level, frames, width, height, tuning, phenotype]) =>
            window.__renderBody({
              body: bodyName, mode: modeName, level, frames, width, height,
              tuning, phenotype,
            }),
          [body, mode, options.level, options.frames, options.width, options.height,
            options.tuning, options.phenotype],
        );
        if (result.error) {
          rows.push({ body, mode, failed: result.error });
          continue;
        }
        const pixels = Buffer.from(result.pixels, "base64");
        const stats = measure(pixels, result.width, result.height);
        const row = { body, mode, ...stats };
        if (options.writePng) {
          const file = join(options.outDir, `${body}--${mode}.png`);
          await mkdir(dirname(file), { recursive: true });
          await writeFile(file, encodePng(pixels, result.width, result.height, options.matte));
          row.png = file;
        }
        rows.push(row);
      }
    }
  } finally {
    await browser.close();
  }

  report(rows);
  const failed = rows.filter((row) => row.failed);
  if (failed.length > 0) process.exitCode = 1;
}

await main();

// --------------------------------------------------------------------- build

/**
 * Bundle the REAL renderer modules rather than lifting shader strings with a
 * regex. The shaders compose from shared chunks by template interpolation, so
 * a regex tests text the GPU never sees -- that mistake has been made here
 * before and the harness looked green while the body was broken.
 */
async function buildBundle() {
  const esbuild = await import(pathToFileURL(esbuildEntry()).href);
  const entry = `
    import { JarvisWebGLRenderer } from "${workerRoot}/src/components/jarvis/JarvisRenderer";
    import { JarvisNeuralRenderer } from "${workerRoot}/src/components/jarvis/v2/JarvisNeuralRenderer";
    import { UltronRenderer } from "${workerRoot}/src/components/ultron/UltronRenderer";
    import { ColossusRenderer } from "${workerRoot}/src/components/colossus/ColossusRenderer";
    import { FamiliarWebGLRenderer } from "${workerRoot}/src/components/familiar/FamiliarWebGLRenderer";
    globalThis.__BODIES = {
      "jarvis-v1": JarvisWebGLRenderer,
      "jarvis-v2": JarvisNeuralRenderer,
      ultron: UltronRenderer,
      colossus: ColossusRenderer,
      // She is as much the reason the raw-text plugin below exists as Jarvis is:
      // familiar.frag is VENDORED and byte-pinned, so a GLSL error in it is
      // SILENT -- the renderer removes its canvas and the stage looks like a CSS
      // problem. This harness is the ten-second way to find out otherwise.
      familiar: FamiliarWebGLRenderer,
    };
  `;
  const built = await esbuild.build({
    stdin: { contents: entry, resolveDir: workerRoot, loader: "ts", sourcefile: "render-bodies-entry.ts" },
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    target: "es2022",
    logLevel: "silent",
    plugins: [rawTextPlugin()],
  });
  return built.outputFiles[0].text;
}

/**
 * Vite's `?raw` suffix, which esbuild knows nothing about. JarvisRenderer loads
 * jarvis.frag and jarvis-post.frag that way -- the bundle's shader is BYTE-PINNED
 * by its manifest, so it has to arrive as the file's own text rather than as a
 * copy anybody could edit here.
 */
function rawTextPlugin() {
  return {
    name: "vite-raw",
    setup(build) {
      build.onResolve({ filter: /\?raw$/ }, (args) => ({
        path: resolve(args.resolveDir, args.path.replace(/\?raw$/, "")),
        namespace: "vite-raw",
      }));
      build.onLoad({ filter: /.*/, namespace: "vite-raw" }, async (args) => ({
        contents: await readFile(args.path, "utf8"),
        loader: "text",
      }));
    },
  };
}

function esbuildEntry() {
  const direct = join(workerRoot, "node_modules/esbuild/lib/main.js");
  if (existsSync(direct)) return direct;
  const store = join(workerRoot, "node_modules/.pnpm");
  const match = readdirSyncSafe(store)
    .filter((name) => name.startsWith("esbuild@"))
    .map((name) => join(store, name, "node_modules/esbuild/lib/main.js"))
    .find((candidate) => existsSync(candidate));
  if (!match) throw new Error("esbuild is not installed under apps/worker/node_modules");
  return match;
}

function readdirSyncSafe(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------- page

function pageHtml(bundleSource) {
  return `<!doctype html>
<meta charset="utf-8">
<style>
  html, body { margin: 0; background: #000; }
  #stage { position: fixed; inset: 0; }
  canvas { display: block; width: 100%; height: 100%; }
</style>
<div id="stage"></div>
<script>${bundleSource}</script>
<script>
window.__renderBody = function (request) {
  var Renderer = globalThis.__BODIES[request.body];
  if (!Renderer) return { error: "unknown body " + request.body };

  var host = document.getElementById("stage");
  host.innerHTML = "";
  host.style.width = request.width + "px";
  host.style.height = request.height + "px";

  // Stub rAF BEFORE mount so the renderer's own loop cannot schedule frames we
  // did not ask for. Every frame in this harness is stepped by hand at a fixed
  // delta -- without that two tuning rounds are not comparable, because the
  // field's look is an integral over however many frames happened to run.
  var realRaf = window.requestAnimationFrame;
  window.requestAnimationFrame = function () { return 0; };

  var renderer = new Renderer({ maxDevicePixelRatio: 1 });
  try {
    renderer.mount(host);
    var status = renderer.status();
    if (status.state !== "running") {
      return { error: status.reason ? status.state + ": " + status.reason : status.state };
    }

    // null unless asked, so an unmeasured body is the default and every figure
    // this prints is comparable with every other run.
    renderer.applyPhenotype(request.phenotype || null);
    // Merged OVER what ships rather than replacing it, so a partial object
    // cannot leave a field undefined and turn arithmetic into NaN.
    if (request.tuning && typeof renderer.setTuning === "function") {
      renderer.setTuning(Object.assign({}, renderer.currentTuning(), request.tuning));
    }
    renderer.update({
      mode: request.mode,
      level: request.level,
      // Eight bands with a plausible tilt rather than a flat line: the ring and
      // facet passes key off the SHAPE of the spectrum, and a flat one hides
      // exactly the pass that is being tuned.
      bands: [0.82, 0.74, 0.61, 0.52, 0.44, 0.33, 0.24, 0.16].map(function (b) {
        return request.mode === "speaking" ? b : b * 0.15;
      }),
      onset: request.mode === "speaking" ? 0.9 : 0,
      micLevel: request.mode === "listening" ? request.level : 0,
    });

    var t = performance.now();
    for (var i = 0; i < request.frames; i++) {
      t += 1000 / 60;
      renderer.frame(t);
    }

    var canvas = host.querySelector("canvas");
    if (!canvas) return { error: "renderer mounted no canvas" };
    // getContext with the same type returns the EXISTING context, so this is
    // the renderer's own GL, read in the same task as the last draw.
    //
    // page.screenshot() is NOT usable here: at higher scene complexity the
    // compositor has already consumed and cleared the drawing buffer by the
    // time it runs, and it photographs an empty canvas while readPixels in this
    // same task sees a full frame. Reproducible, not flaky.
    var gl = canvas.getContext("webgl2");
    if (!gl) return { error: "webgl2 context unavailable for read-back" };
    var w = canvas.width;
    var h = canvas.height;
    var buf = new Uint8Array(w * h * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);

    var binary = "";
    var chunk = 0x8000;
    for (var o = 0; o < buf.length; o += chunk) {
      binary += String.fromCharCode.apply(null, buf.subarray(o, o + chunk));
    }
    return { width: w, height: h, pixels: btoa(binary) };
  } catch (err) {
    return { error: String(err && err.stack ? err.stack : err) };
  } finally {
    try { renderer.destroy(); } catch (err) { void err; }
    window.requestAnimationFrame = realRaf;
  }
};
</script>`;
}

// ----------------------------------------------------------------- measuring

/**
 * GL reads bottom-up; the row order does not matter to any of these statistics,
 * so the buffer is measured as it arrives and only the PNG writer flips it.
 *
 * Alpha matters. The composite pass now writes alpha that follows luminance, so
 * an unpremultiplied read has to be composited over the stage's black before
 * anything is judged -- otherwise a fully transparent pixel carrying leftover
 * colour counts as a bright one.
 */
function measure(pixels, width, height) {
  const x0 = Math.floor(width * 0.25);
  const x1 = Math.ceil(width * 0.75);
  const y0 = Math.floor(height * 0.25);
  const y1 = Math.ceil(height * 0.75);
  const centre = accumulate(pixels, width, x0, y0, x1, y1);
  const whole = accumulate(pixels, width, 0, 0, width, height);
  return {
    sat: centre.sat,
    val: centre.val,
    white: centre.white,
    ink: centre.ink,
    opaqueBlack: whole.opaqueBlack,
    frameSat: whole.sat,
    frameInk: whole.ink,
    edge: edgeColour(pixels, width, height),
    base: baseColour(pixels),
  };
}

/**
 * The colour this body MOSTLY is: the per-channel median of the whole frame.
 *
 * `edge` is the rim, and the rim turned out to be the wrong thing to match a
 * host surface to. Colossus ends in a rectangular vignette of `1 - q^6`, which
 * is nearly flat across the panel and then falls off a cliff in the last few
 * percent -- so a host painted the rim colour still shows the card as a
 * brighter rectangle with a hard edge, which is exactly the defect that was
 * being chased. Matching the median instead puts the host at the board's own
 * colour and leaves the vignette reading as what it is: the body shading its
 * own corners.
 *
 * Median rather than mean or mode. The mean is dragged up by the lamps; the
 * mode does not exist, because the scanline banding gives every row a slightly
 * different value.
 */
function baseColour(pixels) {
  const channel = (offset) => {
    const counts = new Uint32Array(256);
    for (let i = offset; i < pixels.length; i += 4) counts[pixels[i]] += 1;
    const half = (pixels.length / 4) / 2;
    let seen = 0;
    for (let value = 0; value < 256; value++) {
      seen += counts[value];
      if (seen >= half) return value;
    }
    return 0;
  };
  const hex = (value) => value.toString(16).padStart(2, "0");
  return `#${hex(channel(0))}${hex(channel(1))}${hex(channel(2))}`;
}

/**
 * The SEAM COLOUR: the mean of the outermost two-pixel ring, reported
 * unpremultiplied with its alpha.
 *
 * This is the number that decides how a body may be framed, and it is not a
 * matter of taste. A body whose edge alpha is 255 paints an opaque rectangle;
 * put it on a surface of any other colour and the difference IS the inner card,
 * and no amount of removing borders will delete it. A body whose edge alpha is
 * ~0 has nothing to seam against and can float on whatever is behind it.
 *
 * So: alpha 255 means the host surface must be set to this exact hex; alpha 0
 * means the host must be left alone.
 */
function edgeColour(pixels, width, height) {
  const band = 2;
  let r = 0;
  let g = 0;
  let b = 0;
  let a = 0;
  let n = 0;
  for (let y = 0; y < height; y++) {
    const vertical = y < band || y >= height - band;
    for (let x = 0; x < width; x++) {
      if (!vertical && x >= band && x < width - band) continue;
      const i = (y * width + x) * 4;
      r += pixels[i];
      g += pixels[i + 1];
      b += pixels[i + 2];
      a += pixels[i + 3];
      n += 1;
    }
  }
  const hex = (value) => Math.round(value / n).toString(16).padStart(2, "0");
  return { hex: `#${hex(r)}${hex(g)}${hex(b)}`, alpha: Math.round(a / n) };
}

function accumulate(pixels, width, x0, y0, x1, y1) {
  let sat = 0;
  let val = 0;
  let white = 0;
  let ink = 0;
  let opaqueBlack = 0;
  let n = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = (y * width + x) * 4;
      const a = pixels[i + 3] / 255;
      const r = (pixels[i] / 255) * a;
      const g = (pixels[i + 1] / 255) * a;
      const b = (pixels[i + 2] / 255) * a;
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      sat += max <= 0 ? 0 : (max - min) / max;
      val += max;
      if (min >= 0.92) white += 1;
      if (max >= 0.02) ink += 1;
      // OPAQUE AND UNLIT, which is an absence of light that still paints. These
      // bodies write alpha that follows luminance so their dark parts let the
      // page through; a region that is opaque AND black paints black OVER
      // whatever is behind it, which reads as a square flashing across the body.
      if (pixels[i + 3] >= 200 && max < 0.05) opaqueBlack += 1;
      n += 1;
    }
  }
  return {
    sat: round(sat / n),
    val: round(val / n),
    white: round(white / n),
    ink: round(ink / n),
    opaqueBlack: round(opaqueBlack / n),
  };
}

function round(value) { return Math.round(value * 10000) / 10000; }

// ------------------------------------------------------------------- report

function report(results) {
  if (options.json) {
    process.stdout.write(`${JSON.stringify({ level: options.level, frames: options.frames, size: [options.width, options.height], results }, null, 2)}\n`);
    return;
  }
  const header = "body       mode        sat     val    white     ink  opqBlk   frameSat   edge          base";
  process.stdout.write(`${header}\n${"-".repeat(header.length)}\n`);
  for (const row of results) {
    if (row.failed) {
      process.stdout.write(`${pad(row.body, 10)} ${pad(row.mode, 11)} FAILED  ${row.failed}\n`);
      continue;
    }
    process.stdout.write(
      `${pad(row.body, 10)} ${pad(row.mode, 11)}`
      + `${num(row.sat)}${num(row.val)}${num(row.white)}${num(row.ink)}${num(row.opaqueBlack)}${num(row.frameSat)}`
      + `   ${row.edge.hex} a${String(row.edge.alpha).padStart(3, " ")}   ${row.base}\n`,
    );
  }
  const written = results.filter((row) => row.png);
  if (written.length > 0) {
    process.stdout.write(`\n${written.length} PNG(s) in ${options.outDir}\n`);
  }
}

function pad(text, width) { return String(text).padEnd(width, " "); }
function num(value) { return value.toFixed(4).padStart(8, " "); }

// ---------------------------------------------------------------------- png

/**
 * A 40-line PNG writer rather than a dependency, and rather than
 * page.screenshot() -- see the read-back comment in the page above.
 */
function encodePng(pixels, width, height, matte) {
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    // GL's origin is bottom-left, PNG's is top-left.
    const source = (height - 1 - y) * stride;
    raw[y * (stride + 1)] = 0;
    pixels.copy(raw, y * (stride + 1) + 1, source, source + stride);
  }
  // MATTE, or the frame lies about the body. Two of these bodies composite with
  // alpha, and the read-back is UNPREMULTIPLIED -- so an RGBA png of one opens
  // over whatever ground the viewer happens to use, which for most image
  // viewers is white. A hologram designed as light on black, looked at over
  // white, reads as a washed-out grey smear and invites exactly the wrong
  // tuning. Flattening onto the stage's own ground here means the file shows
  // what ships.
  if (matte) {
    for (let i = 0; i < raw.length; i += 1) {
      // Skip the per-row filter byte.
      if (i % (stride + 1) === 0) continue;
      const channel = (i % (stride + 1) - 1) % 4;
      if (channel !== 3) continue;
      const alpha = raw[i] / 255;
      for (let c = 0; c < 3; c++) {
        raw[i - 3 + c] = Math.round(raw[i - 3 + c] * alpha + matte[c] * (1 - alpha));
      }
      raw[i] = 255;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 6 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function chunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, "ascii");
  const body = Buffer.concat([head.subarray(4), data]);
  const tail = Buffer.alloc(4);
  tail.writeUInt32BE(crc32(body) >>> 0, 0);
  return Buffer.concat([head, data, tail]);
}

var crcTable = null;

function crc32(buffer) {
  if (!crcTable) {
    crcTable = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c;
    }
  }
  let crc = -1;
  for (let i = 0; i < buffer.length; i++) crc = crcTable[(crc ^ buffer[i]) & 0xff] ^ (crc >>> 8);
  return crc ^ -1;
}

// ------------------------------------------------------------------ plumbing

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

/**
 * The bundled browser revision pinned by a borrowed Playwright will not in
 * general match what is actually in ~/.cache/ms-playwright, and the mismatch
 * presents as "browser not installed" rather than as a version error. Pick the
 * newest chromium that is present. Note `chrome-linux64`, not `chrome-linux`.
 */
function resolveBrowserExecutable(explicit) {
  if (explicit) return explicit;
  const cache = join(process.env.HOME ?? "", ".cache/ms-playwright");
  const candidates = readdirSyncSafe(cache)
    .filter((name) => /^chromium-\d+$/.test(name))
    .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]))
    .flatMap((name) => [
      join(cache, name, "chrome-linux64/chrome"),
      join(cache, name, "chrome-linux/chrome"),
    ]);
  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) {
    throw new Error(
      `No Chromium under ${cache}. Pass --browser <abs path to the chrome binary>.`,
    );
  }
  return found;
}

function parseArguments(argv) {
  const parsed = {
    help: false,
    json: false,
    writePng: true,
    bodies: [],
    modes: [],
    level: 0.8,
    frames: 180,
    width: 512,
    height: 512,
    outDir: resolve(repoRoot, "work/body-renders"),
    matte: [0, 0, 0],
    tuning: null,
    phenotype: null,
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
      case "--no-matte": parsed.matte = null; break;
      case "--tuning": parsed.tuning = JSON.parse(next()); break;
      case "--phenotype": parsed.phenotype = JSON.parse(next()); break;
      case "--body": parsed.bodies.push(assertOneOf(next(), ALL_BODIES, "--body")); break;
      case "--mode": parsed.modes.push(assertOneOf(next(), ALL_MODES, "--mode")); break;
      case "--level": parsed.level = assertUnit(Number(next()), "--level"); break;
      case "--frames": parsed.frames = assertCount(Number(next()), "--frames"); break;
      case "--size": {
        const [w, h] = next().split("x").map(Number);
        parsed.width = assertCount(w, "--size width");
        parsed.height = assertCount(h, "--size height");
        break;
      }
      case "--out": parsed.outDir = resolve(process.cwd(), next()); break;
      case "--playwright": parsed.playwrightModule = next(); break;
      case "--browser": parsed.browserExecutable = next(); break;
      default: throw new Error(`Unrecognised argument ${arg}`);
    }
  }
  if (parsed.bodies.length === 0) parsed.bodies = [...ALL_BODIES];
  if (parsed.modes.length === 0) parsed.modes = ["standby", "thinking", "speaking"];
  return parsed;
}

function assertOneOf(value, allowed, flag) {
  if (!allowed.includes(value)) {
    throw new Error(`${flag} must be one of ${allowed.join(", ")}; got ${value}`);
  }
  return value;
}

function assertUnit(value, flag) {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error(`${flag} must be between 0 and 1`);
  }
  return value;
}

function assertCount(value, flag) {
  if (!Number.isInteger(value) || value < 1) throw new Error(`${flag} must be a positive integer`);
  return value;
}

function helpText() {
  return `Render the character bodies offscreen and measure the centre of the frame.

  node apps/worker/tests/visual/render-bodies.mjs --playwright <abs path> [options]

  --body <name>      jarvis-v1 | jarvis-v2 | ultron | colossus | familiar;
                     repeatable, default all five
  --mode <name>      ${ALL_MODES.join(" | ")}; repeatable,
                     default standby,thinking,speaking
  --level <0..1>     voice level within the mode (default 0.8)
  --frames <n>       fixed-delta simulation steps before the read (default 180)
  --size <w>x<h>     default 512x512
  --out <dir>        PNG output (default work/body-renders)
  --no-png           numbers only
  --no-matte         keep the PNG's alpha instead of flattening onto black
  --json             machine-readable

Columns: sat/val/white/ink are the centred box of half the width and half the
height -- a quarter of the frame area. frameSat is the whole frame. A centre
that has burned white shows as sat falling and white rising together; a shader
that failed to compile shows as FAILED, and one that compiled but drew nothing
shows as ink near zero.

edge is the mean of the outermost 2px ring with its alpha; base is the
per-channel median of the whole frame. a255 means the body paints an OPAQUE
rectangle, so whatever hosts it has to be painted to match or the difference is
a visible inner card -- and the value to match is BASE, not edge: a body that
ends in a vignette is darkest in its last few pixels, so matching the rim leaves
the rest of it standing proud as a brighter rectangle. a0 means it can float on
any surface and nothing needs matching.
`;
}

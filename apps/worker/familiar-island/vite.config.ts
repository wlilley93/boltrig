// The Familiar island build: the web app's Familiar renderer, as ONE html file
// the iPhone app ships in its bundle and loads from file://.
//
// One file because a bundle resource with sidecar chunks is a relative-URL
// resolution problem on every load; an inlined classic script has no loader at
// all. The script is pinned by hash in the page's own Content-Security-Policy,
// so nothing but exactly this bundle can run in that web view. Deterministic
// by construction (no hashes in names, no timestamps) so that two builds of
// one source tree are byte-identical, which is what lets CI refuse a committed
// page that no longer matches the source.
import { defineConfig, type Plugin } from "vite";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const ENTRY = "familiar-island.js";
const PAGE = "familiar-island.html";

const asText = (source: string | Uint8Array): string =>
  typeof source === "string" ? source : Buffer.from(source).toString("utf8");

/**
 * After the bundle is written: fold the one chunk into the page as a classic
 * inline script, pin it by sha256 in the CSP meta, and emit familiar-island.html
 * in place of the two files.
 */
function inlineIsland(): Plugin {
  return {
    name: "familiar-island-inline",
    enforce: "post",
    generateBundle(_options, bundle) {
      const chunk = Object.values(bundle).find((item) => item.type === "chunk" && item.isEntry);
      const page = Object.values(bundle).find(
        (item) => item.type === "asset" && item.fileName.endsWith(".html"),
      );
      if (chunk?.type !== "chunk") throw new Error("familiar island: no entry chunk in the bundle");
      if (page?.type !== "asset") throw new Error("familiar island: no html page in the bundle");
      const extra = Object.keys(bundle).filter((name) => name !== chunk.fileName && name !== page.fileName);
      if (extra.length) {
        throw new Error(`familiar island must be one file; extra outputs: ${extra.join(", ")}`);
      }
      // The HTML parser reads "<!--" inside a script as the start of an escaped
      // span; no source of ours carries one, and a build that does must fail
      // loudly rather than ship a page Safari parses differently.
      if (chunk.code.includes("<!--")) {
        throw new Error("familiar island: the bundle contains '<!--', unsafe in an inline script");
      }
      // Escaped to a fixpoint, not once: a single replace is the shape the
      // scanner rightly distrusts, even though the input here is our own bundle.
      let code = chunk.code;
      for (let previous = ""; previous !== code;) {
        previous = code;
        code = code.replace(/<\/script/gi, "<\\/script");
      }
      const hash = crypto.createHash("sha256").update(code, "utf8").digest("base64");
      const csp = `default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data:`;

      let html = asText(page.source);
      const scriptTag = /\s*<script\b[^>]*\bsrc="[^"]*familiar-island\.js"[^>]*><\/script>/;
      if (!scriptTag.test(html)) throw new Error("familiar island: no entry script tag to inline");
      html = html.replace(scriptTag, "");
      const cspTag = /<meta http-equiv="Content-Security-Policy" content="[^"]*"\s*\/?>/;
      if (!cspTag.test(html)) throw new Error("familiar island: no Content-Security-Policy meta to pin");
      html = html.replace(cspTag, `<meta http-equiv="Content-Security-Policy" content="${csp}" />`);
      if (!html.includes("</body>")) throw new Error("familiar island: the page has no </body>");
      html = html.replace("</body>", `<script>${code}</script>\n  </body>`);

      delete bundle[chunk.fileName];
      delete bundle[page.fileName];
      this.emitFile({ type: "asset", fileName: PAGE, source: html });
    },
  };
}

export default defineConfig({
  root: HERE,
  base: "./",
  publicDir: false,
  plugins: [inlineIsland()],
  resolve: {
    alias: {
      "@wlilley93/boltrig-web-sdk": path.resolve(HERE, "../../../sdks/web/src/index.ts"),
    },
  },
  build: {
    outDir: "../dist-island",
    emptyOutDir: true,
    target: "safari16",
    modulePreload: false,
    assetsInlineLimit: 0,
    sourcemap: false,
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        format: "iife",
        entryFileNames: ENTRY,
        chunkFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
  clearScreen: false,
});

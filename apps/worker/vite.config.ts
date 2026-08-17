import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

/** Where the shader bench locks its presets in. Read by hand, ported by hand. */
const PRESETS = path.resolve(__dirname, "tests/visual/presets.json");

/**
 * Let the shader bench write a settled preset to DISK.
 *
 * The bench keeps work in progress in localStorage, which is correct for a value
 * still being dragged and useless for a value that has been decided: nothing
 * outside that browser profile can read it, so a look arrived at by eye cannot be
 * ported into the source without being retyped from a screenshot. This route is
 * the way out of the tab.
 *
 * `apply: "serve"` -- DEV ONLY. It never exists in a build, so the shipped image
 * has no write route. That matters more than it looks: this writes a file from an
 * unauthenticated POST, which is fine on a dev server bound to a LAN address and
 * would be a real hole in anything deployed.
 *
 * It writes exactly one known path and only after the payload has been checked,
 * so a malformed or hostile body cannot choose the filename.
 */
function benchPresets(): Plugin {
  return {
    name: "boltrig-bench-presets",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__bench-presets", (req, res, next) => {
        if (req.method !== "POST") return next();
        const chunks: Buffer[] = [];
        req.on("data", (chunk: Buffer) => {
          chunks.push(chunk);
          // A bench preset is a couple of kilobytes. Anything past this is not one.
          if (chunks.reduce((n, c) => n + c.length, 0) > 256 * 1024) req.destroy();
        });
        req.on("end", () => {
          const reply = (code: number, payload: unknown): void => {
            res.statusCode = code;
            res.setHeader("content-type", "application/json");
            res.end(JSON.stringify(payload));
          };
          try {
            const sent = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
              body?: unknown; slot?: unknown; tuning?: unknown; lfos?: unknown;
            };
            const bodyName = String(sent.body ?? "");
            const slot = String(sent.slot ?? "");
            // Whitelisted, not sanitised. A slot name reaches a JSON key, and the
            // set of legitimate ones is small and known -- so it is checked
            // against that set rather than filtered for characters somebody
            // thought of.
            const bodies = ["jarvis", "ultron", "familiar", "colossus"];
            const slots = ["arrival", "standby", "listening", "thinking", "working", "speaking"];
            if (!bodies.includes(bodyName) || !slots.includes(slot)) {
              return reply(400, { error: "unknown body or slot" });
            }
            if (typeof sent.tuning !== "object" || sent.tuning === null) {
              return reply(400, { error: "no tuning" });
            }
            const store = fs.existsSync(PRESETS)
              ? JSON.parse(fs.readFileSync(PRESETS, "utf8")) as Record<string, unknown>
              : {};
            store[`${bodyName}.${slot}`] = {
              tuning: sent.tuning,
              lfos: sent.lfos ?? {},
              savedAt: new Date().toISOString(),
            };
            fs.writeFileSync(PRESETS, `${JSON.stringify(store, null, 2)}\n`);
            return reply(200, { path: "tests/visual/presets.json", count: Object.keys(store).length });
          } catch (error) {
            return reply(400, { error: (error as Error).message });
          }
        });
      });
    },
  };
}

const kernel = process.env.BOLTRIG_KERNEL_URL ?? "http://localhost:8000";
// nginx.conf proxies /voice/ to the channel gateway with the prefix stripped.
// Dev and preview mirror it, so the kernel's relative websocket_url upgrades
// here the same way it does in the shipped image.
const gateway = process.env.BOLTRIG_CHANNEL_GATEWAY_URL ?? "http://localhost:8091";
const voice = {
  target: gateway,
  changeOrigin: true,
  ws: true,
  rewrite: (path: string) => path.replace(/^\/voice/, ""),
};

export default defineConfig({
  base: "./",
  plugins: [react(), benchPresets()],
  resolve: {
    alias: {
      "@wlilley93/boltrig-web-sdk": path.resolve(__dirname, "../../sdks/web/src/index.ts"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    proxy: {
      "/v1": { target: kernel, changeOrigin: true },
      "/healthz": { target: kernel, changeOrigin: true },
      "/readyz": { target: kernel, changeOrigin: true },
      "/voice": voice,
    },
  },
  preview: {
    port: 4180,
    strictPort: true,
    proxy: {
      "/v1": { target: kernel, changeOrigin: true },
      "/healthz": { target: kernel, changeOrigin: true },
      "/readyz": { target: kernel, changeOrigin: true },
      "/voice": voice,
    },
  },
  clearScreen: false,
  envPrefix: ["VITE_", "TAURI_"],
});

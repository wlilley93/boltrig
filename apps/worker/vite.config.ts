import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import crypto from "node:crypto";
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
/**
 * A password on the dev bench, for when the tailnet is not boundary enough.
 *
 * THE TAILNET IS ALREADY THE REAL BOUNDARY: `tailscale serve` is tailnet-only, so
 * reaching this at all needs a device signed into the tailnet. This exists for the
 * belt-and-braces case, and because the bench carries a write route
 * (/__bench-presets) that will happily take a POST from anything that can reach it.
 *
 * THE SECRET IS NEVER IN THE REPO. It is a SHA-256 hash supplied through
 * BOLTRIG_BENCH_AUTH as `user:hexhash`, so the plaintext lives only wherever the
 * operator typed it -- a systemd Environment= line, or a shell. A password
 * committed to a git history is a password that has to be rotated, and this repo
 * is on GitHub.
 *
 * IT DOES NOT FAIL OPEN ONTO SPECIFIC ROUTES. This guard is registered before
 * every other middleware and covers ALL of them, rather than listing paths to
 * protect: a prefix denylist is what made every newly added FrameGraph route public
 * without anyone noticing, because the list only knew about the routes that existed
 * when it was written. If the variable is unset the guard is not installed at all
 * and the server behaves exactly as before -- which is stated here rather than
 * discovered, and is why the systemd unit sets it.
 */
function benchAuth(): Plugin {
  return {
    name: "boltrig-bench-auth",
    apply: "serve",
    configureServer(server) {
      const configured = process.env.BOLTRIG_BENCH_AUTH ?? "";
      const [user, hash] = configured.split(":");
      if (!user || !hash) return;
      server.middlewares.use((req, res, next) => {
        const header = req.headers.authorization ?? "";
        if (header.startsWith("Basic ")) {
          const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
          const at = decoded.indexOf(":");
          const sent = crypto
            .createHash("sha256")
            .update(decoded.slice(at + 1))
            .digest("hex");
          // Length-checked before the timing-safe compare, because timingSafeEqual
          // THROWS on a length mismatch rather than returning false -- which would
          // turn a wrong-length password into a 500 and a stack trace.
          const ok = decoded.slice(0, at) === user
            && sent.length === hash.length
            && crypto.timingSafeEqual(Buffer.from(sent), Buffer.from(hash));
          if (ok) return next();
        }
        res.statusCode = 401;
        res.setHeader("WWW-Authenticate", 'Basic realm="boltrig bench", charset="UTF-8"');
        res.end("authentication required\n");
      });
    },
  };
}

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
  // benchAuth FIRST: a guard registered after another middleware is a guard that
  // middleware has already answered around.
  plugins: [benchAuth(), react(), benchPresets()],
  resolve: {
    alias: {
      "@wlilley93/boltrig-web-sdk": path.resolve(__dirname, "../../sdks/web/src/index.ts"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    // BOTH WAYS IN, named rather than wildcarded, and the private name is not
    // committed.
    //
    // The dev server is reached two ways: over a direct cable by IP, and over a
    // tailnet through `tailscale serve`, which proxies to that same address. The
    // proxied request arrives carrying the TAILNET Host header, and vite's host
    // check answers it with a 403 -- "this host is not allowed" -- which reads as a
    // tailscale or firewall problem and is neither.
    //
    // Explicit rather than `true`, because that check is the DNS-rebinding defence:
    // with it disabled, any page a browser on this network visits could script
    // requests against this origin, and this server carries a write route
    // (/__bench-presets). Naming the hosts keeps the defence and costs a line.
    //
    // From the ENVIRONMENT, because a tailnet hostname is infrastructure naming and
    // this repo is on GitHub. It is not a credential -- reaching the tailnet needs
    // auth regardless -- but it is a detail of someone's private network and there
    // is no reason for it to be in a public history when a variable does the job.
    allowedHosts: [
      "localhost",
      ...(process.env.BOLTRIG_DEV_ALLOWED_HOSTS ?? "")
        .split(",")
        .map((host) => host.trim())
        .filter(Boolean),
    ],
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

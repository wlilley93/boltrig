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
 * A TOKEN on the dev bench, handed over by the intranet rather than typed.
 *
 * This is the pattern FrameGraph Studio already uses on this box: the intranet at
 * :3000 authenticates a person by their VERIFIED Tailscale identity against a
 * root-owned allowlist, then builds a link to the service carrying that service's
 * own token. One gate, one identity check, and the downstream services trust a
 * secret rather than re-implementing a login each.
 *
 * WHY A RANDOM TOKEN AND NOT A PASSWORD. Nobody ever types this: the link comes
 * from the intranet card. So there is no reason for it to be memorable and every
 * reason for it to be long and random -- and no reason for it to be a password that
 * is reused anywhere else, which is the failure mode a human-chosen one invites.
 *
 * THE SECRET IS NEVER IN THE REPO. BOLTRIG_BENCH_TOKEN comes from
 * /etc/boltrig-bench.env, which the systemd unit reads through an OPTIONAL
 * EnvironmentFile and the intranet reads at request time to build its link. One
 * secret, one home: a copy in either would drift the first time it is rotated, and
 * the card would then hand out a confidently wrong link.
 *
 * A COOKIE, because a query parameter only covers the first request. The bench
 * pulls in dozens of module URLs, the audio clips and the shader sources; gating on
 * ?token= alone would authorise the html and 401 everything it asks for next.
 *
 * IT DOES NOT FAIL OPEN ONTO NEW ROUTES. Registered before every other middleware
 * and covering all of them, rather than naming paths to protect -- a prefix denylist
 * is what quietly made every newly added FrameGraph route public, because the list
 * only knew the routes that existed when it was written. If the variable is unset
 * the guard is not installed and the bench behaves as it always has.
 */
function benchAuth(): Plugin {
  const COOKIE = "boltrig_bench";
  return {
    name: "boltrig-bench-auth",
    apply: "serve",
    configureServer(server) {
      const token = process.env.BOLTRIG_BENCH_TOKEN ?? "";
      if (!token) return;
      const expected = Buffer.from(token);
      const matches = (given: string): boolean => {
        const sent = Buffer.from(given);
        // Length-checked first: timingSafeEqual THROWS on a length mismatch rather
        // than returning false, which would turn a wrong-length token into a 500
        // and a stack trace instead of a refusal.
        return sent.length === expected.length && crypto.timingSafeEqual(sent, expected);
      };

      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? "/", "http://x");
        const fromQuery = url.searchParams.get("token");
        if (fromQuery && matches(fromQuery)) {
          // Set the cookie and REDIRECT to the same URL without the token, so it
          // does not sit in the address bar, in history, or in a referer header.
          url.searchParams.delete("token");
          res.setHeader(
            "Set-Cookie",
            `${COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800`,
          );
          res.statusCode = 302;
          res.setHeader("Location", url.pathname + url.search);
          res.end();
          return;
        }

        const cookie = (req.headers.cookie ?? "")
          .split(";")
          .map((part) => part.trim())
          .find((part) => part.startsWith(`${COOKIE}=`));
        const fromCookie = cookie ? decodeURIComponent(cookie.slice(COOKIE.length + 1)) : "";
        const fromHeader = String(req.headers["x-token"] ?? "");
        if ((fromCookie && matches(fromCookie)) || (fromHeader && matches(fromHeader))) {
          return next();
        }

        res.statusCode = 401;
        res.setHeader("content-type", "text/plain; charset=utf-8");
        res.end("this bench is token-gated; open it from the intranet at :3000\n");
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
        const reply = (code: number, payload: unknown): void => {
          res.statusCode = code;
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify(payload));
        };
        // One entry per body.slot, holding a VERSION LIST: a save appends rather
        // than overwrites, so locking a look in can never destroy the look
        // before it. Entries written by the pre-history format (a bare object)
        // read as a one-version list.
        const asVersions = (entry: unknown): { versions: unknown[] } =>
          entry !== null && typeof entry === "object"
            && Array.isArray((entry as { versions?: unknown[] }).versions)
            ? entry as { versions: unknown[] }
            : { versions: entry === undefined ? [] : [entry] };
        if (req.method === "GET") {
          const store = fs.existsSync(PRESETS)
            ? JSON.parse(fs.readFileSync(PRESETS, "utf8")) as Record<string, unknown>
            : {};
          return reply(200, Object.fromEntries(
            Object.entries(store).map(([key, entry]) => [key, asVersions(entry)]),
          ));
        }
        if (req.method !== "POST") return next();
        const chunks: Buffer[] = [];
        req.on("data", (chunk: Buffer) => {
          chunks.push(chunk);
          // A bench preset is a couple of kilobytes. Anything past this is not one.
          if (chunks.reduce((n, c) => n + c.length, 0) > 256 * 1024) req.destroy();
        });
        req.on("end", () => {
          try {
            const sent = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
              body?: unknown; slot?: unknown; tuning?: unknown; lfos?: unknown;
              label?: unknown;
            };
            const bodyName = String(sent.body ?? "");
            const slot = String(sent.slot ?? "");
            // Whitelisted, not sanitised. A slot name reaches a JSON key, and the
            // set of legitimate ones is small and known -- so it is checked
            // against that set rather than filtered for characters somebody
            // thought of.
            const bodies = ["jarvis", "ultron", "familiar", "colossus"];
            // "baseline" is a slot in the store though not a render state: the
            // ground look every state is measured from, versioned like the rest.
            const slots = ["arrival", "standby", "listening", "thinking", "working", "speaking", "baseline"];
            if (!bodies.includes(bodyName) || !slots.includes(slot)) {
              return reply(400, { error: "unknown body or slot" });
            }
            if (typeof sent.tuning !== "object" || sent.tuning === null) {
              return reply(400, { error: "no tuning" });
            }
            const store = fs.existsSync(PRESETS)
              ? JSON.parse(fs.readFileSync(PRESETS, "utf8")) as Record<string, unknown>
              : {};
            const key = `${bodyName}.${slot}`;
            const version: Record<string, unknown> = {
              tuning: sent.tuning,
              lfos: sent.lfos ?? {},
              savedAt: new Date().toISOString(),
            };
            if (typeof sent.label === "string" && sent.label.trim() !== "") {
              version.label = sent.label.trim().slice(0, 120);
            }
            const entry = asVersions(store[key]);
            entry.versions.push(version);
            store[key] = entry;
            fs.writeFileSync(PRESETS, `${JSON.stringify(store, null, 2)}\n`);
            return reply(200, { path: "tests/visual/presets.json", versions: entry.versions.length });
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

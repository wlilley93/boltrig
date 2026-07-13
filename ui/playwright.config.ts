// UI browser-test harness ([2026] VJS-COUNTY 2, order
// 2026-VJS-CC-BOLTRIG-UI-TEST-HARNESS-001). Chromium ONLY, fully hermetic:
// no model keys, no credentials, no egress.
//
// Two local servers back the smoke:
//   1. the REAL kernel (e2e/kernel.py): in-memory store, header-trusting dev
//      principal resolver (create_app's non-production default; the UI sends
//      its x-boltrig-* dev-identity headers), and a ChatService with NO turn
//      executor, so a chat turn yields the deterministic
//      "(no runtime configured)" reply (boltrig/fleet/chat.py).
//   2. vite preview over the built dist, proxying /v1 + /healthz to (1)
//      (the preview proxy in vite.config.ts).
//
// Override the interpreter that boots the kernel with BOLTRIG_E2E_PYTHON
// (e.g. a repo venv); it must have the boltrig package's deps importable.

import { defineConfig, devices } from "@playwright/test";

const PYTHON = process.env.BOLTRIG_E2E_PYTHON || "python3";

function portFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer TCP port between 1 and 65535`);
  }
  return port;
}

const KERNEL_PORT = portFromEnv("BOLTRIG_E2E_KERNEL_PORT", 8791);
const UI_PORT = portFromEnv("BOLTRIG_E2E_UI_PORT", 4173);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // one deterministic smoke; no retries hiding flakes, no parallel workers needed
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} e2e/kernel.py`,
      url: `http://127.0.0.1:${KERNEL_PORT}/healthz`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { BOLTRIG_E2E_KERNEL_PORT: String(KERNEL_PORT) },
    },
    {
      // build then serve the BUILT UI (vite preview over dist), so the smoke
      // exercises the same artifact the nginx image ships.
      command: `pnpm run build && pnpm exec vite preview --host 127.0.0.1 --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { BOLTRIG_KERNEL_URL: `http://127.0.0.1:${KERNEL_PORT}` },
    },
  ],
});

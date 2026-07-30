// Worker browser acceptance: Chromium drives the built Worker payload against
// the same real, credential-free in-memory kernel used by the Operator smoke.
// The dev principal headers authenticate only this loopback test context; no
// model/provider key, stored credential, or external service is involved.

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

const KERNEL_PORT = portFromEnv("BOLTRIG_E2E_KERNEL_PORT", 8792);
const WORKER_PORT = portFromEnv("BOLTRIG_E2E_UI_PORT", 4180);

export default defineConfig({
  testDir: "./e2e-worker",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${WORKER_PORT}`,
    extraHTTPHeaders: {
      "x-boltrig-tenant": "default",
      "x-boltrig-subject": "e2e-worker",
      "x-boltrig-tier": "human",
      "x-boltrig-role": "org-admin",
      "x-boltrig-grants": "*",
    },
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
      command: `pnpm --dir ../apps/worker run build && pnpm --dir ../apps/worker exec vite preview --host 127.0.0.1 --port ${WORKER_PORT} --strictPort`,
      url: `http://127.0.0.1:${WORKER_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { BOLTRIG_KERNEL_URL: `http://127.0.0.1:${KERNEL_PORT}` },
    },
  ],
});

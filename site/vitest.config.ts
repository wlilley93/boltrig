import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "happy-dom",
    globals: false,
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["**/*.test.{ts,tsx}", "**/*.d.ts"],
      reporter: ["text-summary", "json-summary"],
      // Initial non-regression floor. The line debt is explicit and must ratchet
      // upward as the site interaction suite expands.
      thresholds: {
        lines: 1,
        statements: 1,
        functions: 70,
        branches: 70,
      },
    },
  },
  esbuild: {
    jsx: "automatic",
  },
});

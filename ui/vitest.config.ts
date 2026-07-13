import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "happy-dom",
    globals: false,
    exclude: ["e2e/**", "**/node_modules/**", "**/dist/**"],
    coverage: {
      include: ["src/**/*.{ts,tsx}", "config/**/*.ts"],
      exclude: ["**/*.test.{ts,tsx}", "**/*.d.ts"],
      reporter: ["text-summary", "json-summary"],
      thresholds: {
        lines: 35,
        statements: 35,
        functions: 28,
        branches: 60,
      },
    },
  },
});

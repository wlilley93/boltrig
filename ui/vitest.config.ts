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
      reporter: ["json-summary"],
    },
  },
});

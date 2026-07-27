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
      // RE-BASELINED for vitest 4, whose v8 provider remaps coverage through the
      // AST to SOURCE constructs instead of counting the transpiled bundle. The
      // denominators move enormously, and not all in the same direction:
      //
      //   metric      vitest 3               vitest 4
      //   statements  55.70% (16451/29532)   42.60% ( 3890/9131)
      //   branches    71.57% ( 2457/3433)    38.01% ( 2734/7192)
      //   functions   47.29% (  770/1628)    39.70% ( 1202/3027)
      //   lines       55.70% (16451/29532)   43.77% ( 3487/7965)
      //
      // Statements fell 3x because the old denominator included generated code.
      // Branches DOUBLED, 3,433 -> 7,192: the previous measure could not see half
      // the branches in this codebase, so a 60% branch gate was being met against
      // a denominator missing half its subject. Nothing about the tests changed
      // between those two runs - only what was being counted.
      //
      // These numbers are lower and TRUE, and they are a ratchet: raise them as
      // coverage rises, never lower them to fit.
      thresholds: {
        lines: 43,
        statements: 42,
        functions: 39,
        branches: 37,
      },
    },
  },
});
